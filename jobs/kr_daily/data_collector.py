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


_NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://finance.naver.com/",
}

def _naver_soup(url: str, params: dict = None) -> BeautifulSoup:
    resp = requests.get(url, params=params, headers=_NAVER_HEADERS, timeout=10)
    resp.encoding = "euc-kr"
    return BeautifulSoup(resp.text, "lxml")


def get_latest_trading_date() -> str:
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
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    result = {}
    for key, ticker in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            df = fdr.DataReader(ticker, date_fmt, date_fmt)
            if df.empty:
                result[key] = {}
                continue
            row = df.iloc[-1]
            close = float(row["Close"])
            change_raw = float(row.get("Change", 0))
            change_pct = change_raw * 100
            prev_close = close / (1 + change_raw) if change_raw != -1 else close
            result[key] = {
                "close": round(close, 2),
                "change": round(close - prev_close, 2),
                "change_pct": round(change_pct, 2),
                "volume": int(row.get("Volume", 0)),
            }
        except Exception as e:
            print(f"  [{key}] 지수 수집 실패: {e}")
            result[key] = {}
    return result


def _fmt_amount(amount: int) -> str:
    """순매수거래대금(원) → 억원 단위 문자열"""
    if amount >= 0:
        return f"+{amount // 100_000_000:,}억"
    return f"{amount // 100_000_000:,}억"


def get_investor_data(date_str: str) -> dict:
    """외국인/기관/연기금 KOSPI 순매수 TOP3 수집 (pykrx)
    date_str: YYYYMMDD 형식
    """
    try:
        from pykrx import stock as pyk
    except ImportError:
        print("  [수급] pykrx 미설치 — 수급 데이터 생략")
        return {"investor_top3": {}, "foreign_net": None, "institution_net": None}

    investor_map = {
        "외국인": "외국인",
        "기관":   "기관합계",
        "연기금": "연기금등",
    }
    result = {}
    for label, key in investor_map.items():
        try:
            df = pyk.get_market_net_purchases_of_equities_by_ticker(
                date_str, date_str, "KOSPI", key
            )
            if df is None or df.empty:
                result[label] = []
                continue
            # 순매수거래대금 컬럼 탐색
            amt_col = next(
                (c for c in ["순매수거래대금", "순매수금액", "NetBuyValue"] if c in df.columns),
                None,
            )
            if amt_col is None:
                result[label] = []
                continue
            # 종목명 컬럼 탐색 (없으면 index = 티커코드 사용)
            name_col = "종목명" if "종목명" in df.columns else None
            top3 = []
            for _, row in df.nlargest(3, amt_col).iterrows():
                name = str(row[name_col]) if name_col else str(row.name)
                top3.append({"name": name, "net_amount": int(row[amt_col])})
            result[label] = top3
        except Exception as e:
            print(f"  [{label}] 수급 수집 실패: {e}")
            result[label] = []

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

        gainers = [{"name": str(r["Name"]), "change_pct": round(float(r[chg_col]), 2)}
                   for _, r in df_top5.nlargest(5, chg_col).iterrows()]
        losers = [{"name": str(r["Name"]), "change_pct": round(float(r[chg_col]), 2)}
                  for _, r in df_top5.nsmallest(5, chg_col).iterrows()]

        return {"top_gainers": gainers, "top_losers": losers, "stock_pct_map": stock_pct_map}

    except Exception as e:
        print(f"  [FDR 종목] 실패: {e}")
        return {"top_gainers": [], "top_losers": [], "stock_pct_map": {}}


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
            pct_raw = cols[1].get_text(strip=True)
            if not name or not pct_raw:
                continue
            is_neg = "-" in pct_raw
            pct_val = re.sub(r"[^\d.]", "", pct_raw)
            try:
                pct = float(pct_val) * (-1 if is_neg else 1)
                sectors.append({"name": name, "change_pct": round(pct, 2)})
            except ValueError:
                continue

        if not sectors:
            return {"top_sectors": [], "bottom_sectors": []}

        sectors.sort(key=lambda x: x["change_pct"], reverse=True)
        return {
            "top_sectors": sectors[:3],
            "bottom_sectors": sectors[-3:][::-1],
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
        resp = requests.get(
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
    investor_data = get_investor_data(date)
    stock_result = get_top_stocks(date)
    sector_data = get_sector_data(date)
    news = get_news()
    featured = get_featured_stock_news()

    return {
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        **index_data,
        **investor_data,
        **sector_data,
        **stock_result,
        "news": news,
        "crawled_news_features": featured,
    }
