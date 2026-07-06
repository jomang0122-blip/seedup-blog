# -*- coding: utf-8 -*-
import json
import os
import re
import time
import requests
from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr
from bs4 import BeautifulSoup
from shared.utils import fetch_with_retry


_NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://finance.naver.com/",
}

def _naver_soup(url: str, params: dict = None) -> BeautifulSoup:
    resp = fetch_with_retry(url, params=params, headers=_NAVER_HEADERS, timeout=10)
    resp.encoding = "euc-kr"
    return BeautifulSoup(resp.text, "lxml")


def get_latest_trading_date() -> str:
    """FDR로 최근 거래일 탐색 (빠른 응답, 날짜 확인용)."""
    date = datetime.today()
    for _ in range(10):
        date_str = date.strftime("%Y-%m-%d")
        try:
            df = fdr.DataReader("KS11", date_str, date_str)
            if not df.empty:
                return date.strftime("%Y%m%d")
        except Exception:
            pass
        date -= timedelta(days=1)
    raise RuntimeError("최근 거래일을 찾을 수 없습니다.")


def get_index_data(date_str: str) -> dict:
    """KOSPI/KOSDAQ 지수 데이터 수집 (네이버 모바일 API — 실시간)."""
    naver_map = {
        "kospi":  "KOSPI",
        "kosdaq": "KOSDAQ",
    }
    result = {}
    for key, code in naver_map.items():
        try:
            resp = fetch_with_retry(
                f"https://m.stock.naver.com/api/index/{code}/basic",
                headers=_NAVER_HEADERS,
                timeout=10,
            )
            data = resp.json()
            close      = float(data.get("closePrice", "0").replace(",", ""))
            change     = float(data.get("compareToPreviousClosePrice", "0").replace(",", ""))
            change_pct = float(data.get("fluctuationsRatio", "0").replace(",", ""))
            result[key] = {
                "close":      round(close, 2),
                "change":     round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume":     0,
            }
        except Exception as e:
            print(f"  [{key}] 지수 수집 실패: {e}")
            result[key] = {}
    return result


_ETF_PREFIXES = (
    "KODEX", "TIGER", "RISE", "SOL", "ACE", "KBSTAR", "ARIRANG", "HANARO",
    "KOSEF", "TREX", "SMART", "파워", "FOCUS", "TIMEFOLIO", "PLUS", "1Q", "WON",
)

def _is_etf(name: str) -> bool:
    return any(name.startswith(p) for p in _ETF_PREFIXES)


def _clean_stock_df(df: pd.DataFrame, chg_col: str) -> pd.DataFrame:
    df = df.copy()
    df[chg_col] = pd.to_numeric(df[chg_col], errors="coerce")
    vol_col = next((c for c in ["Volume", "거래량"] if c in df.columns), None)
    if vol_col:
        df = df[pd.to_numeric(df[vol_col], errors="coerce") > 0]
    df = df[~df["Name"].astype(str).str.match(r".*우[BC]?$")]
    return df.dropna(subset=[chg_col])


def _build_stock_maps() -> dict:
    """KOSPI+KOSDAQ 전종목 등락률·시가총액 사전과, TOP5 산출용 정제 DataFrame 생성.

    뉴스기반 특징주 검증(stock_pct_map/stock_cap_map 필요)이 TOP5 산출보다
    먼저 실행되어야 해서(뉴스기반으로 확정된 종목을 TOP5 후보에서 제외하기 위해)
    맵 생성과 TOP5 산출을 분리했다.
    """
    df_kospi = fdr.StockListing("KOSPI")
    chg_col = next(
        (c for c in ["ChagesRatio", "ChangeRatio", "Change%", "Chg%"] if c in df_kospi.columns),
        None
    )
    if chg_col is None:
        raise ValueError(f"등락률 컬럼 없음: {df_kospi.columns.tolist()}")

    df_kospi = _clean_stock_df(df_kospi, chg_col)
    stock_pct_map = {
        str(r["Name"]): round(float(r[chg_col]), 2)
        for _, r in df_kospi.iterrows()
    }
    stock_cap_map = {}
    if "Marcap" in df_kospi.columns:
        stock_cap_map = {
            str(r["Name"]): float(r["Marcap"])
            for _, r in df_kospi.iterrows()
            if pd.notna(r["Marcap"])
        }

    try:
        df_kosdaq = fdr.StockListing("KOSDAQ")
        kq_chg = next(
            (c for c in ["ChagesRatio", "ChangeRatio", "Change%", "Chg%"] if c in df_kosdaq.columns),
            None
        )
        if kq_chg:
            df_kosdaq = _clean_stock_df(df_kosdaq, kq_chg)
            for _, r in df_kosdaq.iterrows():
                name = str(r["Name"])
                if name not in stock_pct_map:
                    stock_pct_map[name] = round(float(r[kq_chg]), 2)
                if name not in stock_cap_map and "Marcap" in df_kosdaq.columns and pd.notna(r["Marcap"]):
                    stock_cap_map[name] = float(r["Marcap"])
    except Exception as e:
        print(f"  [종목] KOSDAQ 추가 실패: {e}")

    return {
        "df_kospi": df_kospi,
        "chg_col": chg_col,
        "stock_pct_map": stock_pct_map,
        "stock_cap_map": stock_cap_map,
    }


def get_top_stocks(stock_maps: dict, exclude_names: set = None) -> dict:
    """시총 1조원 이상 종목 중 등락률 TOP5 산출.

    exclude_names 제공 시 해당 종목은 TOP5 후보에서 제외한다 — 뉴스기반
    특징주로 이미 확정된 종목이 상승/하락 특징주에 중복 노출되는 대신,
    그 다음 순위 종목이 자리를 채우도록 하기 위함.
    """
    exclude_names = exclude_names or set()
    try:
        df_kospi = stock_maps["df_kospi"]
        chg_col = stock_maps["chg_col"]

        df_top5 = df_kospi.copy()
        if "Marcap" in df_top5.columns:
            df_top5 = df_top5[pd.to_numeric(df_top5["Marcap"], errors="coerce") > 1_000_000_000_000]
        if exclude_names:
            df_top5 = df_top5[~df_top5["Name"].astype(str).isin(exclude_names)]

        _UPPER_LIMIT_THRESHOLD = 29.0
        gainers = [
            {
                "name": str(r["Name"]),
                "change_pct": round(float(r[chg_col]), 2),
                "is_upper_limit": round(float(r[chg_col]), 2) >= _UPPER_LIMIT_THRESHOLD,
            }
            for _, r in df_top5.nlargest(5, chg_col).iterrows()
        ]
        losers = [
            {
                "name": str(r["Name"]),
                "change_pct": round(float(r[chg_col]), 2),
                "is_upper_limit": False,
            }
            for _, r in df_top5.nsmallest(5, chg_col).iterrows()
        ]

        return {
            "top_gainers": gainers,
            "top_losers": losers,
            "stock_pct_map": stock_maps["stock_pct_map"],
            "stock_cap_map": stock_maps["stock_cap_map"],
        }

    except Exception as e:
        print(f"  [FDR 종목] 실패: {e}")
        return {"top_gainers": [], "top_losers": [], "stock_pct_map": {}, "stock_cap_map": {}}


_MIN_SECTOR_STOCK_CAP = 1_000_000_000_000  # 1조원 — 섹터 대표종목·뉴스 특징주 잡주 차단 기준 (급등락 TOP과 동일 기준)


def _crawl_sector_top_stocks(
    no: str, top_n: int = 2, is_rising: bool = True,
    stock_cap_map: dict = None, min_cap: float = _MIN_SECTOR_STOCK_CAP,
) -> tuple:
    """업종 상세 페이지(type_5 테이블)에서 대표종목 + 업종폭(breadth) 통계 수집.

    is_rising=True  → 상승률 높은 순 (상승 섹터용)
    is_rising=False → 하락률 큰 순  (하락 섹터용)
    stock_cap_map 제공 시 시가총액 min_cap 미만 종목(잡주)은 대표종목에서 제외.

    Returns: (대표종목 리스트, breadth 통계 dict 또는 None)
    breadth = {"total": 구성종목 수, "same_dir": 섹터 방향과 같은 방향 종목 수,
               "ratio": same_dir/total}
    breadth는 시총 필터 적용 전 전체 구성종목(ETF·우선주 제외) 기준 —
    "섹터 등락이 업종 전반의 움직임인지, 소수 종목이 견인한 것인지"를
    구성종목 등락 분포라는 숫자로만 판정하기 위한 데이터. 뉴스 헤드라인
    문구에 의존하는 판정은 표현 다양성 때문에 구조적으로 오판이 반복되어
    (실사고 2건: 업종명 정확매칭 방식 전체 오탐, '관련주' 키워드 방식은
    호남 테마를 업종 이슈로 오인) 숫자 기반으로 재설계했다.
    """
    url = "https://finance.naver.com/sise/sise_group_detail.naver"
    try:
        resp = fetch_with_retry(url, params={"type": "upjong", "no": no}, headers=_NAVER_HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "lxml")
        # 종목 목록은 type_5 테이블 (td 10개, tds[0]=종목명, tds[3]=등락률)
        table = soup.find("table", {"class": "type_5"})
        if not table:
            return [], None
        all_stocks = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            name_tag = tds[0].find("a")
            if not name_tag:
                continue
            name = name_tag.get_text(strip=True)
            if not name or _is_etf(name):
                continue
            # 우선주 제외 (종목명 끝 '우', '우B', '우C' 등)
            if re.match(r".*우[BC]?$", name):
                continue
            pct_raw = tds[3].get_text(strip=True)
            is_neg = "-" in pct_raw
            pct_val = re.sub(r"[^\d.]", "", pct_raw)
            if not pct_val:
                continue
            try:
                pct = float(pct_val) * (-1 if is_neg else 1)
                all_stocks.append({"name": name, "change_pct": round(pct, 2)})
            except ValueError:
                continue

        # 업종폭 통계 — 전체 구성종목 중 섹터 방향과 같은 방향으로 움직인 비율
        breadth = None
        if all_stocks:
            same_dir = sum(
                1 for s in all_stocks
                if (s["change_pct"] > 0) == is_rising and s["change_pct"] != 0
            )
            breadth = {
                "total": len(all_stocks),
                "same_dir": same_dir,
                "ratio": round(same_dir / len(all_stocks), 2),
            }

        # 대표종목: 시가총액 필터 — 잡주(소형 테마주) 대표종목 선정 차단
        candidates = [
            s for s in all_stocks
            if stock_cap_map is None or stock_cap_map.get(s["name"], 0) >= min_cap
        ]
        # 상승 섹터: 상승률 높은 순 / 하락 섹터: 하락률 큰 순
        candidates.sort(key=lambda x: x["change_pct"], reverse=is_rising)
        return candidates[:top_n], breadth
    except Exception as e:
        print(f"  [섹터상세-{no}] 실패: {e}")
        return [], None


def get_sector_data(date_str: str = None, stock_cap_map: dict = None) -> dict:
    try:
        main_resp = requests.get(
            "https://finance.naver.com/sise/sise_group.nhn",
            params={"type": "upjong"},
            headers=_NAVER_HEADERS,
            timeout=10,
        )
        main_resp.encoding = "cp949"
        soup = BeautifulSoup(main_resp.text, "lxml")

        table = soup.find("table", {"class": "type_1"}) or soup.find("table")
        if not table:
            return {"top_sectors": [], "bottom_sectors": []}

        sectors = []
        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            a_tag = cols[0].find("a")
            name = a_tag.get_text(strip=True) if a_tag else cols[0].get_text(strip=True)
            # 업종 상세 페이지 no 추출
            href = a_tag.get("href", "") if a_tag else ""
            no_match = re.search(r"no=(\d+)", href)
            no = no_match.group(1) if no_match else None
            pct_raw = cols[1].get_text(strip=True)
            if not name or not pct_raw:
                continue
            is_neg = "-" in pct_raw
            pct_val = re.sub(r"[^\d.]", "", pct_raw)
            try:
                pct = float(pct_val) * (-1 if is_neg else 1)
                sectors.append({"name": name, "change_pct": round(pct, 2), "no": no})
            except ValueError:
                continue

        if not sectors:
            return {"top_sectors": [], "bottom_sectors": []}

        sectors.sort(key=lambda x: x["change_pct"], reverse=True)
        top3 = sectors[:3]
        bot3 = sectors[-3:][::-1]

        # 상위 섹터: 상승률 높은 순 / 하위 섹터: 하락률 큰 순
        for s in top3:
            if s.get("no"):
                s["top_stocks"], s["breadth"] = _crawl_sector_top_stocks(s["no"], top_n=2, is_rising=True, stock_cap_map=stock_cap_map)
            else:
                s["top_stocks"], s["breadth"] = [], None
            _set_breadth_verdict(s)
        for s in bot3:
            if s.get("no"):
                s["top_stocks"], s["breadth"] = _crawl_sector_top_stocks(s["no"], top_n=2, is_rising=False, stock_cap_map=stock_cap_map)
            else:
                s["top_stocks"], s["breadth"] = [], None
            _set_breadth_verdict(s)

        _attach_sector_stock_news(top3 + bot3, date_str=date_str)

        return {
            "top_sectors": top3,
            "bottom_sectors": bot3,
        }
    except Exception as e:
        print(f"  [섹터] 수집 실패: {e}")
        return {"top_sectors": [], "bottom_sectors": []}


_MIN_BREADTH_SAMPLE = 5  # 구성종목이 이보다 적으면 분포 판정이 무의미 — 판정 보류


def _set_breadth_verdict(sector: dict) -> None:
    """섹터 등락이 '업종 전반'인지 '소수 종목 견인'인지 구성종목 등락 분포로 판정.

    뉴스 헤드라인 문구 기반 판정은 표현 다양성 때문에 오판이 구조적으로
    반복되어(2026-07-06 실사고 2건: 업종명 정확매칭 전체 오탐, '관련주'
    키워드는 호남 테마를 업종 이슈로 오인) 숫자 분포 기반으로 재설계했다.

    3구간 판정 — 경계값 부근(예: 51%)에서 이분법이 불안정한 문제를 피하고,
    애매한 구간은 어느 쪽도 단정하지 않는다:
      ratio >= 0.6  → "broad"    (업종 전반 — '동반 강세/약세' 표현 허용)
      ratio <  0.5  → "isolated" (소수 종목 견인 — '동반' 표현 금지)
      0.5~0.6       → "mixed"    (혼재 — 전반/개별 어느 쪽도 단정 금지)
    breadth가 없거나 표본이 적으면 None (판정 보류 — 안전 폴백).
    """
    breadth = sector.get("breadth")
    if not breadth or breadth["total"] < _MIN_BREADTH_SAMPLE:
        sector["breadth_verdict"] = None
        return
    if breadth["ratio"] >= 0.6:
        verdict = "broad"
    elif breadth["ratio"] < 0.5:
        verdict = "isolated"
    else:
        verdict = "mixed"
    sector["breadth_verdict"] = verdict
    label = {"broad": "업종 전반", "isolated": "소수 견인", "mixed": "혼재"}[verdict]
    print(
        f"  [업종폭] {sector['name']}: {breadth['total']}종목 중 {breadth['same_dir']}개 동방향"
        f" ({breadth['ratio']:.0%}) → {label}"
    )


def _attach_sector_stock_news(sectors: list, date_str: str = None) -> None:
    """섹터 대표종목에 검증된 뉴스 헤드라인을 참고용으로 첨부.

    get_stock_news_by_name의 3중 필터(종목명 포함·오늘 날짜·방향 일치)를
    거친 헤드라인만 붙는다. 이 뉴스는 AI가 '핵심 흐름 한 줄'을 쓸 때의
    사실 근거로만 쓰이고, 업종 전반/개별 이슈 판정은 breadth 숫자가 담당한다.
    """
    reps = [t for s in sectors for t in s.get("top_stocks", [])]
    if not reps:
        return
    pct_map = {t["name"]: t["change_pct"] for t in reps}
    news_map = get_stock_news_by_name(list(pct_map), date_str=date_str, pct_map=pct_map)
    for s in sectors:
        for t in s.get("top_stocks", []):
            t["news"] = news_map.get(t["name"], "")


def _naver_news_search(query: str, display: int = 3) -> list:
    client_id = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []
    try:
        resp = fetch_with_retry(
            "https://openapi.naver.com/v1/search/news.json",
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": query, "display": display, "sort": "date"},
            timeout=5,
        )
        items = resp.json().get("items", [])
        return [
            {
                "title": re.sub(r"<[^>]+>", "", item["title"]),
                "link": item.get("originallink") or item.get("link", ""),
                "pub_date": item.get("pubDate", ""),
            }
            for item in items
        ]
    except Exception as e:
        print(f"  [뉴스] '{query}' 수집 실패: {e}")
        return []


def get_news(query: str = "코스피 증시 오늘") -> list:
    items = _naver_news_search(query, display=5)
    return [i["title"] for i in items]


def _crawl_featured_stock_news() -> list:
    try:
        url = "https://finance.naver.com/news/news_list.naver"
        params = {"mode": "LSS2D", "section_id": "101", "section_id2": "258"}
        soup = _naver_soup(url, params=params)
        results = []
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True)
            if "[특징주]" in text and text not in results:
                results.append(text)
            if len(results) >= 30:
                break
        return results
    except Exception as e:
        print(f"  [특징주뉴스] 크롤링 실패: {e}")
        return []


def get_featured_stock_news(display: int = 30) -> list:
    """헤드라인 후보 30개 수집 — 뉴스기반 특징주는 4단계 검증(실종목·등락률·시총·오늘뉴스)을
    통과해야 하고, 상승/하락 특징주와 중복되면 제외되므로 후보 풀을 넉넉히 확보해야 함."""
    items = _naver_news_search("[특징주]", display=display)
    results = [i["title"] for i in items if "[특징주]" in i["title"]]
    if results:
        return results[:30]
    return _crawl_featured_stock_news()


_UP_WORDS = ("급등", "상한가", "신고가", "강세", "상승", "↑")
_DOWN_WORDS = ("급락", "하한가", "약세", "하락", "↓")


def _direction_consistent(title: str, change_pct: float) -> bool:
    """헤드라인의 방향 표현이 오늘 등락 부호와 모순되지 않는지 확인.

    하락 종목에 '급등'류 단어만 있는(하락 단어는 없는) 기사, 그 반대의 경우를
    걸러낸다. 상승·하락 단어가 둘 다 있거나 둘 다 없으면 판단하지 않고 통과.
    보수적 드롭 가드 — 잘못 걸러도 결과는 '뉴스 생략'이라 안전하다.
    """
    has_up = any(w in title for w in _UP_WORDS)
    has_down = any(w in title for w in _DOWN_WORDS)
    if change_pct > 0 and has_down and not has_up:
        return False
    if change_pct < 0 and has_up and not has_down:
        return False
    return True


def get_stock_news_by_name(names: list, date_str: str = None, pct_map: dict = None) -> dict:
    """특징주 종목명별 뉴스 개별 검색. {종목명: 헤드라인} 반환.
    '[특징주] 종목명' 검색만 수행 — fallback 없음.
    오래된 일반 뉴스가 오늘 이유로 둔갑하는 AI 환각 방지.

    3중 필터 (전부 보수적 — 애매하면 뉴스 없음 처리):
    1. 종목명 포함: 네이버 뉴스 검색 API는 형태소 관련도 매칭이라 검색어에
       종목명을 넣어도 무관 기사가 올 수 있음(실사례: '금호타이어' 검색에
       'GS 데이터센터' 기사). 헤드라인에 종목명 문자열이 실제 포함된 것만 채택.
    2. 오늘 날짜(date_str 제공 시): 과거 급등 기사가 오늘 하락 종목에 붙는
       사고 방지(실사례: -10% SK이터닉스에 과거 '20% 급등' 기사가 붙음).
    3. 방향 일치(pct_map 제공 시): 오늘 기사라도 장중 방향 반전 등으로
       헤드라인 방향 표현이 종가 부호와 모순되면 제외.
    """
    result = {}
    for name in names:
        items = _naver_news_search(f"[특징주] {name}", display=10)
        matched = [i for i in items if name in i["title"]]
        if date_str:
            matched = [i for i in matched if _is_today_news(i.get("pub_date", ""), date_str)]
        if pct_map is not None and name in pct_map:
            matched = [i for i in matched if _direction_consistent(i["title"], pct_map[name])]
        if matched:
            result[name] = matched[0]["title"]
        print(f"  [종목뉴스] {name}: {'있음' if name in result else '없음(후보 ' + str(len(items)) + '건 중 통과 없음)'}")
    return result


def _parse_name_from_headline(headline: str, stock_pct_map: dict = None) -> str:
    """'[특징주] 종목명, ...' 형태 헤드라인에서 종목명만 추출.

    '[특징주]' 뒤 첫 어절을 곧바로 종목명으로 쓰지 않는다. 종목명 자체에 조사와
    같은 글자가 포함될 수 있어(예: '금호타이어'의 '이어', 'SK하이닉스'의 '하이') 문자열
    패턴만으로는 종목명 경계를 정확히 알 수 없기 때문이다. 대신 stock_pct_map(오늘
    실제 거래된 전체 종목명 사전)에 존재하는 후보 중 가장 긴 것을 종목명으로 채택해
    경계를 확정하고, 그 뒤에 주어 패턴(쉼표 또는 주격조사 이/가/은/는)이 바로 오는
    경우에만 그 종목을 '문장의 실제 행위 주체'로 인정한다.

    '[특징주] 종목명과의 계약'처럼 종목명이 상대방·수식 대상으로만 언급된 경우
    (조사 없이 다른 말이 붙거나 '~과의/~와의/~ 협력사인/~ 관련주인' 등)는 주어
    패턴이 없으므로 보수적으로 거부한다.
    """
    m = re.match(r"\[특징주\]\s*(.{1,20})", headline)
    if not m:
        return ""
    tail = m.group(1)

    if not stock_pct_map:
        return ""

    best_name = ""
    for candidate in stock_pct_map:
        if not candidate or not tail.startswith(candidate):
            continue
        if len(candidate) <= len(best_name):
            continue
        rest = tail[len(candidate):]
        if re.match(r"^\s*,", rest) or re.match(r"^(이|가|은|는)(?!\S)", rest):
            best_name = candidate
    return best_name


def _is_today_news(pub_date: str, date_str: str) -> bool:
    """Naver pubDate(RFC822)가 date_str(YYYYMMDD) 날짜인지 확인."""
    try:
        from email.utils import parsedate
        parsed = parsedate(pub_date)
        if parsed:
            return f"{parsed[0]}{parsed[1]:02d}{parsed[2]:02d}" == date_str
    except Exception:
        pass
    return False


def extract_and_verify_featured_stocks(
    headlines: list,
    stock_pct_map: dict,
    date_str: str,
    min_change_pct: float = 2.0,
    stock_cap_map: dict = None,
    min_cap: float = _MIN_SECTOR_STOCK_CAP,
) -> list:
    """crawled_news_features 헤드라인 기반 뉴스기반 특징주 4단계 검증.

    ① stock_pct_map 교차검증 — 오늘 실제 거래된 종목인지 (허구 종목 차단)
    ② 등락률 임계값 |change_pct| >= min_change_pct — 보합 종목 차단
    ③ 시가총액 min_cap 이상 — 잡주(소형 테마주) 차단
    ④ 네이버 뉴스 API 오늘 날짜 기사 확인 — 오래된/허구 뉴스 차단

    Returns: [{"name": str, "change_pct": float, "news": str}]
    """
    seen = set()
    verified = []

    for headline in headlines:
        name = _parse_name_from_headline(headline, stock_pct_map)
        if not name or name in seen:
            continue
        seen.add(name)

        # ① 실제 종목 확인 (stock_pct_map = 오늘 전 종목 등락률 맵)
        if name not in stock_pct_map:
            print(f"  [검증①실패] {name}: 주가 데이터 없음")
            continue

        change_pct = stock_pct_map[name]

        # ② 등락률 임계값 — 보합 종목 제외
        if abs(change_pct) < min_change_pct:
            print(f"  [검증②실패] {name}: {change_pct:+.2f}% < ±{min_change_pct}% (보합)")
            continue

        # ③ 시가총액 필터 — 잡주 차단
        if stock_cap_map is not None and stock_cap_map.get(name, 0) < min_cap:
            print(f"  [검증③실패] {name}: 시총 {stock_cap_map.get(name, 0) / 1e8:.0f}억 < {min_cap / 1e8:.0f}억")
            continue

        # ④ 네이버 뉴스 오늘 날짜 기사 확인 — 오늘 날짜 + 종목명이 실제 헤드라인에
        # 포함된 기사만 채택(검색어에 종목명을 넣어도 관련도 매칭으로 무관한 기사가
        # 섞여 들어올 수 있음 — get_stock_news_by_name과 동일한 이유의 방어).
        # 여러 건 중에서는 이미 파싱해 검증①~③을 통과한 원본 headline과 가장 가까운
        # (원본 헤드라인과 동일하거나, 없으면 최신) 기사를 우선한다.
        items = _naver_news_search(f"[특징주] {name}", display=10)
        today_items = [
            i for i in items
            if _is_today_news(i.get("pub_date", ""), date_str) and name in i["title"]
        ]
        if not today_items:
            print(f"  [검증④실패] {name}: 오늘({date_str}) 종목명 포함 [특징주] 뉴스 없음")
            continue

        exact_match = [i for i in today_items if i["title"] == headline]
        chosen = exact_match[0] if exact_match else today_items[0]

        verified.append({
            "name": name,
            "change_pct": change_pct,
            "news": chosen["title"],
        })
        print(f"  [검증완료] {name}: {change_pct:+.2f}% / {chosen['title'][:50]}")

    return verified


def get_index_data_historical(date_str: str) -> dict:
    """과거 날짜 지수 데이터 — FDR 과거 종가 조회.

    get_index_data()는 네이버 모바일 실시간 API만 써서 date_str과 무관하게 항상
    "오늘" 값을 반환한다(--date 백필 파라미터가 무시되는 원인). 실제 과거 날짜가
    지정된 경우에만 이 함수를 사용해 그 날짜의 정확한 종가·등락률을 조회한다.
    """
    result = {}
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    for key, code in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            start = (datetime.strptime(date_fmt, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
            close_series = fdr.DataReader(code, start, date_fmt)["Close"].dropna()
            if len(close_series) < 2:
                result[key] = {}
                continue
            close, prev = float(close_series.iloc[-1]), float(close_series.iloc[-2])
            result[key] = {
                "close":      round(close, 2),
                "change":     round(close - prev, 2),
                "change_pct": round((close - prev) / prev * 100, 2),
                "volume":     0,
            }
        except Exception as e:
            print(f"  [{key}] 과거 지수 수집 실패: {e}")
            result[key] = {}
    return result


def collect_all(date: str = None) -> dict:
    is_backfill = date is not None
    if date is None:
        date = get_latest_trading_date()

    print(f"[데이터 수집] 날짜: {date}" + (" [백필 모드]" if is_backfill else ""))

    if is_backfill:
        # 실시간 전용 소스(네이버 수급·FDR 당일 시세·네이버 섹터·뉴스)는 과거 날짜를
        # 지원하지 않아 그대로 두면 "오늘" 데이터가 과거 날짜로 잘못 표시된다.
        # 지수(FDR 과거 종가 조회 가능)만 정확히 채우고, 나머지는 비워서
        # 각 섹션의 기존 skip-note 로직이 자연스럽게 해당 섹션을 생략하도록 한다.
        print("  [백필 모드] 지수는 과거 종가로 정확히 채움 / 종목·섹터·뉴스는 실시간 전용 소스라 생략")
        index_data = get_index_data_historical(date)
        stock_result = {"top_gainers": [], "top_losers": [], "stock_pct_map": {}, "stock_cap_map": {}}
        sector_data = {"top_sectors": [], "bottom_sectors": []}
        news = []
        featured = []
        stock_news_map = {}
        featured_verified = []
    else:
        index_data = get_index_data(date)
        news = get_news()
        featured = get_featured_stock_news()

        # 뉴스기반 특징주를 상승/하락 특징주(TOP5)보다 먼저 확정한다.
        # TOP5 산출에 필요한 stock_pct_map/stock_cap_map만 먼저 만들고,
        # 뉴스기반 검증 통과 종목은 TOP5 후보에서 제외해 같은 종목이
        # "상승 특징주"와 "뉴스기반 특징주" 양쪽에 중복 노출되지 않게 한다.
        stock_maps = _build_stock_maps()
        print("[뉴스기반 특징주 검증]")
        featured_verified = extract_and_verify_featured_stocks(
            featured,
            stock_maps["stock_pct_map"],
            date,
            stock_cap_map=stock_maps["stock_cap_map"],
        )
        print(f"  → 검증 완료: {len(featured_verified)}개")

        stock_result = get_top_stocks(
            stock_maps, exclude_names={v["name"] for v in featured_verified}
        )
        sector_data = get_sector_data(date, stock_cap_map=stock_result.get("stock_cap_map", {}))

        # 특징주 종목별 개별 뉴스 검색 (top_gainers/losers용)
        stock_names = [
            s["name"] for s in
            stock_result.get("top_gainers", []) + stock_result.get("top_losers", [])
        ]
        stock_news_map = get_stock_news_by_name(
            stock_names, date_str=date, pct_map=stock_maps["stock_pct_map"]
        )

    return {
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        **index_data,
        **sector_data,
        **stock_result,
        "news": news,
        "crawled_news_features": featured,
        "stock_news_map": stock_news_map,
        "featured_verified": featured_verified,
    }
