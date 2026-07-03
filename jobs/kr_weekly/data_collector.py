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
from shared.utils import fetch_with_retry

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


_NAVER_INDEX_CODE = {"kospi": "KOSPI", "kosdaq": "KOSDAQ"}


def get_index_data_weekly(this_fri_str: str, prev_fri_str: str) -> dict:
    """KOSPI/KOSDAQ 주간 등락률 (이전 금요일 종가는 FDR 과거 조회, 이번 금요일 종가는 네이버 모바일 API).

    이번 금요일 종가를 FDR 과거 데이터로 조회하면 장마감 직후 최신값 반영이 지연돼
    실제 종가와 다른 값이 나올 수 있음(실측: 마감 2시간 후에도 구값 노출, 2026-07-03).
    kr_daily가 이미 검증한 네이버 모바일 API(실시간)로 이번 금요일 종가만 별도 조회.
    """
    result = {}
    prev_fri_dt = datetime.strptime(prev_fri_str, "%Y%m%d")
    for key, ticker in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            # 이전 금요일 종가 — FDR 과거 데이터 (직전 5일 창으로 공휴일 대비)
            start = (prev_fri_dt - timedelta(days=5)).strftime("%Y-%m-%d")
            end   = prev_fri_dt.strftime("%Y-%m-%d")
            df = fdr.DataReader(ticker, start, end)
            if df.empty:
                result[key] = {}
                continue
            prev_close = float(df["Close"].dropna().iloc[-1])

            # 이번 금요일 종가 — 네이버 모바일 API 실시간 (kr_daily와 동일 방식)
            code = _NAVER_INDEX_CODE[key]
            resp = fetch_with_retry(
                f"https://m.stock.naver.com/api/index/{code}/basic",
                headers=_NAVER_HEADERS, timeout=10,
            )
            this_close = float(resp.json().get("closePrice", "0").replace(",", ""))
            if not this_close:
                result[key] = {}
                continue

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


def _week_trading_days(prev_fri_str: str, this_fri_str: str) -> list:
    """이전 금요일 다음 월요일 ~ 이번 금요일의 평일 목록."""
    start = datetime.strptime(prev_fri_str, "%Y%m%d") + timedelta(days=3)
    end   = datetime.strptime(this_fri_str, "%Y%m%d")
    days  = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return days


def get_investor_data_weekly(this_fri_str: str, prev_fri_str: str) -> dict:
    """데일리 저장된 수급 JSON 파일(data/investor_YYYYMMDD.json)을 읽어 주간 합산 TOP3 산출."""
    import json as _json
    from pathlib import Path

    DATA_DIR = Path(__file__).parent.parent.parent / "data"

    trading_days = _week_trading_days(prev_fri_str, this_fri_str)
    print(f"  [수급] 주간 거래일: {trading_days}")

    accumulated = {"외국인": {}, "기관": {}}
    loaded_days = 0

    for day in trading_days:
        fname = DATA_DIR / f"investor_{day}.json"
        if not fname.exists():
            print(f"  [수급] {day} 파일 없음")
            continue
        try:
            payload = _json.loads(fname.read_text(encoding="utf-8"))
            loaded_days += 1
            for label in ["외국인", "기관"]:
                inv = payload.get(label, {})
                for item in inv.get("buy", []):
                    accumulated[label][item["name"]] = (
                        accumulated[label].get(item["name"], 0) + item["net_amount"]
                    )
                for item in inv.get("sell", []):
                    # sell net_amount는 음수로 저장됨
                    accumulated[label][item["name"]] = (
                        accumulated[label].get(item["name"], 0) + item["net_amount"]
                    )
        except Exception as e:
            print(f"  [수급] {day} 읽기 실패: {e}")

    print(f"  [수급] 주간 데이터 로드: {loaded_days}/{len(trading_days)}일")

    if loaded_days == 0:
        return {}

    result = {}
    for label, acc in accumulated.items():
        if not acc:
            result[label] = {"buy": [], "sell": []}
            continue
        sorted_items = sorted(acc.items(), key=lambda x: x[1], reverse=True)
        buy3  = [{"name": n, "net_amount": v} for n, v in sorted_items[:3]       if v > 0]
        sell3 = [{"name": n, "net_amount": v} for n, v in sorted_items[-3:][::-1] if v < 0]
        print(f"  [{label}] 주간 순매수 TOP3: {[b['name'] for b in buy3]}")
        result[label] = {"buy": buy3, "sell": sell3}

    return result


def _ohlcv_snapshot(pyk, date_str: str, direction: int = 1) -> pd.DataFrame:
    """단일 날짜 OHLCV 스냅샷 취득 — 없으면 direction 방향으로 최대 3일 탐색."""
    for delta in range(4):
        d = (datetime.strptime(date_str, "%Y%m%d") + timedelta(days=delta * direction)).strftime("%Y%m%d")
        try:
            df = pyk.get_market_ohlcv_by_ticker(d, market="KOSPI")
            if df is not None and not df.empty:
                print(f"  [종목] OHLCV 스냅샷: {d}")
                return df
        except Exception:
            pass
    return None


def get_top_stocks_weekly(this_fri_str: str, prev_fri_str: str) -> dict:
    """KOSPI 주간 급등락 TOP5.
    주초·주말 단일 OHLCV 스냅샷을 비교해 주간 등락률 산출 (범위 쿼리 대신 단일 쿼리 2회).
    """
    try:
        from pykrx import stock as pyk

        prev_fri_dt = datetime.strptime(prev_fri_str, "%Y%m%d")
        week_mon_str = (prev_fri_dt + timedelta(days=3)).strftime("%Y%m%d")

        # 주초(월요일→이후 방향) / 주말(금요일→이전 방향) 스냅샷
        df_start = _ohlcv_snapshot(pyk, week_mon_str, direction=1)
        df_end   = _ohlcv_snapshot(pyk, this_fri_str, direction=-1)

        if df_start is None or df_end is None:
            print("  [주간 종목] OHLCV 스냅샷 취득 실패")
            return {"top_gainers": [], "top_losers": []}

        close_col = next((c for c in ["종가", "Close"] if c in df_end.columns), None)
        cap_col   = next((c for c in ["시가총액", "Marcap"] if c in df_end.columns), None)

        if close_col is None:
            print(f"  [주간 종목] 종가 컬럼 없음: {df_end.columns.tolist()}")
            return {"top_gainers": [], "top_losers": []}

        common = df_end.index.intersection(df_start.index)
        end_c   = pd.to_numeric(df_end.loc[common, close_col],   errors="coerce")
        start_c = pd.to_numeric(df_start.loc[common, close_col], errors="coerce")

        mask = (start_c > 1000) & (end_c > 1000)
        if cap_col:
            caps = pd.to_numeric(df_end.loc[common, cap_col], errors="coerce")
            mask = mask & (caps > 1_000_000_000_000)  # 1조원 — kr_daily 급등락 TOP 기준과 통일

        pct = ((end_c - start_c) / start_c * 100)[mask].dropna()

        def _to_item(ticker, val):
            try:
                name = pyk.get_market_ticker_name(ticker)
            except Exception:
                name = ticker
            return {"name": name, "ticker": ticker, "change_pct": round(float(val), 2)}

        gainers = [g for g in [_to_item(t, v) for t, v in pct.nlargest(10).items()]
                   if not re.match(r".*우[BC]?$", g["name"])][:5]
        losers  = [l for l in [_to_item(t, v) for t, v in pct.nsmallest(10).items()]
                   if not re.match(r".*우[BC]?$", l["name"])][:5]
        print(f"  [주간 종목] 급등 TOP3: {[g['name'] for g in gainers[:3]]}")
        return {"top_gainers": gainers, "top_losers": losers}

    except Exception as e:
        print(f"  [주간 종목] 수집 실패: {e}")
        return {"top_gainers": [], "top_losers": []}


def get_sector_data() -> dict:
    """네이버 금융 업종 등락률 (상위 3개, 하위 3개)."""
    try:
        resp = fetch_with_retry(
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
            resp = fetch_with_retry(
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
