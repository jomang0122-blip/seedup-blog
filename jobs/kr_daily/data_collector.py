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
    "KOSEF", "TREX", "SMART", "파워", "FOCUS", "TIMEFOLIO",
)

def _is_etf(name: str) -> bool:
    return any(name.startswith(p) for p in _ETF_PREFIXES)


def _crawl_deal_rank_iframe(investor_gubun: str, direction: str, label: str) -> list:
    """네이버 sise_deal_rank_iframe에서 외국인/기관 매수/매도 대금 TOP3 수집.

    investor_gubun: "9000"=외국인, "1000"=기관
    direction: "buy" | "sell"
    tds 구조: tds[0]=종목명, tds[1]=수량(천주, 부호 포함), tds[2]=대금(백만원, 부호 포함)

    주의: 이 테이블은 '순매수/순매도'가 아니라 방향별 거래대금 합계 순위이다.
      - type=buy  -> 해당 투자자가 매수한 금액이 큰 종목 TOP (매수총액)
      - type=sell -> 해당 투자자가 매도한 금액이 큰 종목 TOP (매도총액, tds[2]가 이미 음수)
    따라서 동일 종목이 buy TOP3과 sell TOP3에 동시 등장할 수 있다.
    예) 삼성전자: 외국인 매수 1,083억 + 외국인 매도 38,498억 -> 순매수는 -37,415억

    Returns: [{"name": str, "amount_won": int(원, buy=양수, sell=음수)}]
    """
    url = (
        f"https://finance.naver.com/sise/sise_deal_rank_iframe.naver"
        f"?sosok=01&investor_gubun={investor_gubun}&type={direction}"
    )
    try:
        resp = fetch_with_retry(url, headers=_NAVER_HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", {"class": "type_1"})
        if not table:
            print(f"  [수급-{label}-{direction}] 테이블 없음")
            return []
        result = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            name_tag = tds[0].find("a")
            if not name_tag:
                continue
            name = name_tag.get_text(strip=True)
            if not name or _is_etf(name):
                continue
            # tds[2]는 sell 테이블에서 이미 음수로 제공됨 -> abs() 로 절대값 추출
            amt_raw = tds[2].get_text(strip=True).replace(",", "").replace("-", "")
            if not amt_raw.isdigit():
                continue
            # 단위: 백만원 -> 원 변환 / buy=양수, sell=음수
            amt_won = int(amt_raw) * 1_000_000
            if direction == "sell":
                amt_won = -amt_won
            result.append({"name": name, "amount_won": amt_won})
            if len(result) >= 3:
                break
        print(f"  [수급-{label}-{direction}] {len(result)}개: {[r['name'] for r in result]}")
        return result
    except Exception as e:
        print(f"  [수급-{label}-{direction}] 실패: {e}")
        return []


def get_investor_data(date_str: str = None) -> dict:
    """네이버 sise_deal_rank_iframe에서 외국인/기관 매수대금/매도대금 TOP3 수집.
    반환값의 buy/sell은 순매수/순매도가 아닌 방향별 거래대금 합계 TOP이다.
    동일 종목이 buy와 sell에 동시 등장하는 것은 정상 (삼성전자 등 대형주).
    """
    investors = {
        "외국인": "9000",
        "기관":   "1000",
    }
    result = {}
    for label, gubun in investors.items():
        buy3  = _crawl_deal_rank_iframe(gubun, "buy",  label)
        sell3 = _crawl_deal_rank_iframe(gubun, "sell", label)
        result[label] = {"buy": buy3, "sell": sell3}
    return {"investor_top3": result, "foreign_net": None, "institution_net": None}


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

        return {"top_gainers": gainers, "top_losers": losers, "stock_pct_map": stock_pct_map}

    except Exception as e:
        print(f"  [FDR 종목] 실패: {e}")
        return {"top_gainers": [], "top_losers": [], "stock_pct_map": {}}


def _crawl_sector_top_stocks(no: str, top_n: int = 2) -> list:
    """업종 상세 페이지(type_5 테이블)에서 등락률 기준 상위 종목 top_n개 반환."""
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
        stocks.sort(key=lambda x: x["change_pct"], reverse=True)
        return stocks[:top_n]
    except Exception as e:
        print(f"  [섹터상세-{no}] 실패: {e}")
        return []


def get_sector_data(date_str: str = None) -> dict:
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

        # 상위/하위 섹터별 종목 상위 2개 추가 수집
        for s in top3 + bot3:
            if s.get("no"):
                s["top_stocks"] = _crawl_sector_top_stocks(s["no"], top_n=2)
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
            if len(results) >= 15:
                break
        return results
    except Exception as e:
        print(f"  [특징주뉴스] 크롤링 실패: {e}")
        return []


def get_featured_stock_news(display: int = 15) -> list:
    items = _naver_news_search("[특징주]", display=display)
    results = [i["title"] for i in items if "[특징주]" in i["title"]]
    if results:
        return results[:15]
    return _crawl_featured_stock_news()


def collect_all(date: str = None) -> dict:
    if date is None:
        date = get_latest_trading_date()

    print(f"[데이터 수집] 날짜: {date}")

    index_data = get_index_data(date)
    # get_investor_data()는 kr_weekly용으로 보존 — kr_daily에서는 미사용
    stock_result = get_top_stocks(date)
    sector_data = get_sector_data(date)
    news = get_news()
    featured = get_featured_stock_news()

    return {
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        **index_data,
        **sector_data,
        **stock_result,
        "news": news,
        "crawled_news_features": featured,
    }
