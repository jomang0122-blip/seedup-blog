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


def get_top_stocks(date_str: str) -> dict:
    try:
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

        df_top5 = df_kospi.copy()
        if "Marcap" in df_top5.columns:
            df_top5 = df_top5[pd.to_numeric(df_top5["Marcap"], errors="coerce") > 1_000_000_000_000]

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
            "stock_pct_map": stock_pct_map,
            "stock_cap_map": stock_cap_map,
        }

    except Exception as e:
        print(f"  [FDR 종목] 실패: {e}")
        return {"top_gainers": [], "top_losers": [], "stock_pct_map": {}, "stock_cap_map": {}}


_MIN_SECTOR_STOCK_CAP = 1_000_000_000_000  # 1조원 — 섹터 대표종목·뉴스 특징주 잡주 차단 기준 (급등락 TOP과 동일 기준)


def _crawl_sector_top_stocks(
    no: str, top_n: int = 2, is_rising: bool = True,
    stock_cap_map: dict = None, min_cap: float = _MIN_SECTOR_STOCK_CAP,
) -> list:
    """업종 상세 페이지(type_5 테이블)에서 종목 수집.
    is_rising=True  → 상승률 높은 순 (상승 섹터용)
    is_rising=False → 하락률 큰 순  (하락 섹터용)
    stock_cap_map 제공 시 시가총액 min_cap 미만 종목(잡주) 제외.
    """
    url = "https://finance.naver.com/sise/sise_group_detail.naver"
    try:
        resp = fetch_with_retry(url, params={"type": "upjong", "no": no}, headers=_NAVER_HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "lxml")
        # 종목 목록은 type_5 테이블 (td 10개, tds[0]=종목명, tds[3]=등락률)
        table = soup.find("table", {"class": "type_5"})
        if not table:
            return []
        stocks = []
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
            # 시가총액 필터 — 잡주(소형 테마주) 대표종목 선정 차단
            if stock_cap_map is not None and stock_cap_map.get(name, 0) < min_cap:
                continue
            pct_raw = tds[3].get_text(strip=True)
            is_neg = "-" in pct_raw
            pct_val = re.sub(r"[^\d.]", "", pct_raw)
            if not pct_val:
                continue
            try:
                pct = float(pct_val) * (-1 if is_neg else 1)
                stocks.append({"name": name, "change_pct": round(pct, 2)})
            except ValueError:
                continue
        # 상승 섹터: 상승률 높은 순 / 하락 섹터: 하락률 큰 순
        stocks.sort(key=lambda x: x["change_pct"], reverse=is_rising)
        return stocks[:top_n]
    except Exception as e:
        print(f"  [섹터상세-{no}] 실패: {e}")
        return []


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
                s["top_stocks"] = _crawl_sector_top_stocks(s["no"], top_n=2, is_rising=True, stock_cap_map=stock_cap_map)
                print(f"  [섹터종목] {s['name']}: {[t['name'] for t in s['top_stocks']]}")
            else:
                s["top_stocks"] = []
        for s in bot3:
            if s.get("no"):
                s["top_stocks"] = _crawl_sector_top_stocks(s["no"], top_n=2, is_rising=False, stock_cap_map=stock_cap_map)
                print(f"  [섹터종목] {s['name']}: {[t['name'] for t in s['top_stocks']]}")
            else:
                s["top_stocks"] = []

        return {
            "top_sectors": top3,
            "bottom_sectors": bot3,
        }
    except Exception as e:
        print(f"  [섹터] 수집 실패: {e}")
        return {"top_sectors": [], "bottom_sectors": []}


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


def get_stock_news_by_name(names: list) -> dict:
    """특징주 종목명별 뉴스 개별 검색. {종목명: 헤드라인} 반환.
    '[특징주] 종목명' 검색만 수행 — fallback 없음.
    오래된 일반 뉴스가 오늘 이유로 둔갑하는 AI 환각 방지.
    """
    result = {}
    for name in names:
        items = _naver_news_search(f"[특징주] {name}", display=3)
        if items:
            result[name] = items[0]["title"]
        print(f"  [종목뉴스] {name}: {'있음' if name in result else '없음'}")
    return result


def _parse_name_from_headline(headline: str) -> str:
    """'[특징주] 종목명, ...' 형태 헤드라인에서 종목명만 추출."""
    m = re.match(r"\[특징주\]\s*([^\s,·…]+)", headline)
    return m.group(1).strip() if m else ""


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
        name = _parse_name_from_headline(headline)
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

        # ④ 네이버 뉴스 오늘 날짜 기사 확인
        items = _naver_news_search(f"[특징주] {name}", display=5)
        today_items = [i for i in items if _is_today_news(i.get("pub_date", ""), date_str)]
        if not today_items:
            print(f"  [검증④실패] {name}: 오늘({date_str}) [특징주] 뉴스 없음")
            continue

        verified.append({
            "name": name,
            "change_pct": change_pct,
            "news": today_items[0]["title"],
        })
        print(f"  [검증완료] {name}: {change_pct:+.2f}% / {today_items[0]['title'][:50]}")

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
        stock_result = get_top_stocks(date)
        sector_data = get_sector_data(date, stock_cap_map=stock_result.get("stock_cap_map", {}))
        news = get_news()
        featured = get_featured_stock_news()

        # 특징주 종목별 개별 뉴스 검색 (top_gainers/losers용)
        stock_names = [
            s["name"] for s in
            stock_result.get("top_gainers", []) + stock_result.get("top_losers", [])
        ]
        stock_news_map = get_stock_news_by_name(stock_names)

        # 뉴스기반 특징주 3단계 검증
        print("[뉴스기반 특징주 검증]")
        featured_verified = extract_and_verify_featured_stocks(
            featured,
            stock_result.get("stock_pct_map", {}),
            date,
            stock_cap_map=stock_result.get("stock_cap_map", {}),
        )
        print(f"  → 검증 완료: {len(featured_verified)}개")

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
