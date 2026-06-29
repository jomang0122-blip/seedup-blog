# -*- coding: utf-8 -*-
"""
국내증시 위클리 데이터 수집
- KOSPI/KOSDAQ 주간 등락률 (이전 금요일 종가 기준)
- 외국인/기관/연기금 주간 수급 TOP3 (pykrx)
- 주간 급등락 종목 TOP5 (pykrx 금요일 비교)
- 주간 섹터 등락률 (네이버 금융)
- 주간 뉴스 (네이버 API)
"""
import os
import re
import requests
from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr
from bs4 import BeautifulSoup
import pytz

KST = pytz.timezone("Asia/Seoul")

_NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://finance.naver.com/",
}


def get_week_dates() -> tuple[str, str, str, str]:
    """이번 주 금요일 및 이전 금요일 날짜 계산.
    토요일 실행 기준: 이번 금요일 = 어제.
    Returns: (this_fri_YYYYMMDD, prev_fri_YYYYMMDD, week_start_display, week_end_display)
    """
    kst_now = datetime.now(KST)
    days_since_friday = (kst_now.weekday() - 4) % 7
    this_friday = kst_now - timedelta(days=days_since_friday)
    prev_friday = this_friday - timedelta(days=7)
    return (
        this_friday.strftime("%Y%m%d"),
        prev_friday.strftime("%Y%m%d"),
        prev_friday.strftime("%Y-%m-%d"),
        this_friday.strftime("%Y-%m-%d"),
    )


def get_index_data_weekly(this_fri_str: str, prev_fri_str: str) -> dict:
    """KOSPI/KOSDAQ 주간 등락률 (이전 금요일 → 이번 금요일 종가 비교)."""
    result = {}
    prev_fri_dt = datetime.strptime(prev_fri_str, "%Y%m%d")
    for key, ticker in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            start = (prev_fri_dt - timedelta(days=3)).strftime("%Y-%m-%d")
            end   = datetime.strptime(this_fri_str, "%Y%m%d").strftime("%Y-%m-%d")
            df = fdr.DataReader(ticker, start, end)
            if df.empty:
                result[key] = {}
                continue
            fridays = df[df.index.dayofweek == 4]["Close"].dropna()
            if len(fridays) >= 2:
                prev_close = float(fridays.iloc[-2])
                this_close = float(fridays.iloc[-1])
            else:
                prev_close = float(df["Close"].iloc[0])
                this_close = float(df["Close"].iloc[-1])
            weekly_pct = (this_close - prev_close) / prev_close * 100
            result[key] = {
                "close":         round(this_close, 2),
                "prev_close":    round(prev_close, 2),
                "weekly_change": round(this_close - prev_close, 2),
                "weekly_pct":    round(weekly_pct, 2),
            }
        except Exception as e:
            print(f"  [{key}] 지수 수집 실패: {e}")
            result[key] = {}
    return result


def _fmt_amount(amount: int) -> str:
    val = amount // 100_000_000
    return f"+{val:,}억" if amount >= 0 else f"{val:,}억"


def get_investor_data_weekly(this_fri_str: str, prev_fri_str: str) -> dict:
    """외국인/기관/연기금 KOSPI 주간 순매수 TOP3 (pykrx)."""
    try:
        from pykrx import stock as pyk
    except ImportError:
        print("  [수급] pykrx 미설치 — 수급 데이터 생략")
        return {}

    prev_fri_dt = datetime.strptime(prev_fri_str, "%Y%m%d")
    week_start  = (prev_fri_dt + timedelta(days=3)).strftime("%Y%m%d")  # 월요일
    week_end    = this_fri_str

    investor_map = {"외국인": "외국인", "기관": "기관합계", "연기금": "연기금등"}
    result = {}
    for label, key in investor_map.items():
        try:
            df = pyk.get_market_net_purchases_of_equities_by_ticker(
                week_start, week_end, "KOSPI", key
            )
            if df is None or df.empty:
                print(f"  [{label}] DataFrame 비어 있음 (None or empty)")
                result[label] = {"buy": [], "sell": []}
                continue
            print(f"  [{label}] 컬럼: {df.columns.tolist()}")
            amt_col = next(
                (c for c in ["순매수거래대금", "순매수금액", "NetBuyValue"] if c in df.columns), None
            )
            if amt_col is None:
                print(f"  [{label}] 순매수 컬럼 없음 — 가용 컬럼: {df.columns.tolist()}")
                result[label] = {"buy": [], "sell": []}
                continue
            name_col = "종목명" if "종목명" in df.columns else None

            def _row_to_item(row):
                name = str(row[name_col]) if name_col else str(row.name)
                return {"name": name, "net_amount": int(row[amt_col])}

            buy3  = [_row_to_item(r) for _, r in df.nlargest(3, amt_col).iterrows()]
            sell3 = [_row_to_item(r) for _, r in df.nsmallest(3, amt_col).iterrows()]
            print(f"  [{label}] 순매수 TOP3: {[s['name'] for s in buy3]}")
            result[label] = {"buy": buy3, "sell": sell3}
        except Exception as e:
            print(f"  [{label}] 주간 수급 수집 실패: {e}")
            result[label] = {"buy": [], "sell": []}
    return result


def get_top_stocks_weekly(this_fri_str: str, prev_fri_str: str) -> dict:
    """KOSPI 주간 급등락 TOP5 (pykrx get_market_price_change_by_ticker 사용)."""
    try:
        from pykrx import stock as pyk

        prev_fri_dt = datetime.strptime(prev_fri_str, "%Y%m%d")
        week_start  = (prev_fri_dt + timedelta(days=3)).strftime("%Y%m%d")  # 월요일

        df = pyk.get_market_price_change_by_ticker(week_start, this_fri_str, "KOSPI")
        if df is None or df.empty:
            print("  [주간 종목] pykrx 결과 없음")
            return {"top_gainers": [], "top_losers": []}

        pct_col   = "등락률"   if "등락률"   in df.columns else None
        close_col = "종가"     if "종가"     in df.columns else None
        cap_col   = "시가총액" if "시가총액" in df.columns else None

        if pct_col is None:
            print(f"  [주간 종목] 등락률 컬럼 없음: {df.columns.tolist()}")
            return {"top_gainers": [], "top_losers": []}

        # 1000원 미만 제외
        if close_col:
            df = df[pd.to_numeric(df[close_col], errors="coerce") > 1000]
        # 시가총액 5천억 미만 소형주 제외
        if cap_col:
            df = df[pd.to_numeric(df[cap_col], errors="coerce") > 500_000_000_000]

        df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce")
        df = df.dropna(subset=[pct_col])

        def _to_item(ticker, pct):
            try:
                name = pyk.get_market_ticker_name(ticker)
            except Exception:
                name = ticker
            return {"name": name, "ticker": ticker, "change_pct": round(float(pct), 2)}

        gainers = [_to_item(t, p) for t, p in df[pct_col].nlargest(5).items()]
        losers  = [_to_item(t, p) for t, p in df[pct_col].nsmallest(5).items()]
        return {"top_gainers": gainers, "top_losers": losers}

    except Exception as e:
        print(f"  [주간 종목] 수집 실패: {e}")
        return {"top_gainers": [], "top_losers": []}


def get_sector_data() -> dict:
    """네이버 금융 업종 등락률 (상위 3개, 하위 3개)."""
    try:
        resp = requests.get(
            "https://finance.naver.com/sise/sise_group.nhn",
            params={"type": "upjong"},
            headers=_NAVER_HEADERS,
            timeout=10,
        )
        resp.encoding = "cp949"
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", {"class": "type_1"}) or soup.find("table")
        if not table:
            return {"top_sectors": [], "bottom_sectors": []}

        sectors = []
        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            a_tag = cols[0].find("a")
            name  = a_tag.get_text(strip=True) if a_tag else cols[0].get_text(strip=True)
            pct_raw = cols[1].get_text(strip=True)
            if not name or not pct_raw:
                continue
            is_neg  = "-" in pct_raw
            pct_val = re.sub(r"[^\d.]", "", pct_raw)
            try:
                pct = float(pct_val) * (-1 if is_neg else 1)
                sectors.append({"name": name, "change_pct": round(pct, 2)})
            except ValueError:
                continue

        sectors.sort(key=lambda x: x["change_pct"], reverse=True)
        return {"top_sectors": sectors[:3], "bottom_sectors": sectors[-3:][::-1]}
    except Exception as e:
        print(f"  [섹터] 수집 실패: {e}")
        return {"top_sectors": [], "bottom_sectors": []}


def get_news_weekly() -> list:
    """네이버 API로 주간 국내 증시 뉴스 수집."""
    client_id     = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    queries = ["코스피 주간 시황", "코스피 증시 이번주"]
    for query in queries:
        if not client_id or not client_secret:
            break
        try:
            resp = requests.get(
                "https://openapi.naver.com/v1/search/news.json",
                headers={
                    "X-Naver-Client-Id": client_id,
                    "X-Naver-Client-Secret": client_secret,
                },
                params={"query": query, "display": 5, "sort": "date"},
                timeout=5,
            )
            items = resp.json().get("items", [])
            titles = [re.sub(r"<[^>]+>", "", i["title"]) for i in items if i.get("title")]
            if titles:
                return titles[:5]
        except Exception as e:
            print(f"  [뉴스] '{query}' 수집 실패: {e}")
    return []


def collect_all() -> dict:
    print("[데이터 수집] 국내증시 위클리")

    this_fri, prev_fri, week_start, week_end = get_week_dates()
    print(f"  주간 범위: {week_start} ~ {week_end} (이전 금요일 기준)")

    index_data    = get_index_data_weekly(this_fri, prev_fri)
    investor_data = get_investor_data_weekly(this_fri, prev_fri)
    stock_data    = get_top_stocks_weekly(this_fri, prev_fri)
    sector_data   = get_sector_data()
    news          = get_news_weekly()

    return {
        "week_start":    week_start,
        "week_end":      week_end,
        "this_fri":      this_fri,
        "kst_date":      datetime.now(KST).strftime("%Y-%m-%d"),
        **index_data,
        "investor_top3": investor_data,
        **stock_data,
        **sector_data,
        "news":          news,
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    data = collect_all()
    print(f"\n주간: {data['week_start']} ~ {data['week_end']}")
    kospi = data.get("kospi", {})
    print(f"KOSPI: {kospi.get('close')} (주간 {kospi.get('weekly_pct'):+.2f}%)")
    print(f"상위 종목: {[s['name'] for s in data.get('top_gainers', [])]}")
    print(f"뉴스: {len(data.get('news', []))}건")
