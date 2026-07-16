# -*- coding: utf-8 -*-
"""
국내증시 월간 결산 데이터 수집
- KOSPI/KOSDAQ 월간 등락률 (전월 말일 종가 기준)
- 이번 달 각 거래일 코스피 등락률 → 최고/최저 상승일·하락일 도출
- 시가총액 상위 10종목 월간 등락 (kr_weekly 함수 재사용)
- 월간 투자자별 순매수 합계 (kr_weekly 함수 재사용)
- 월간 뉴스 (네이버 API)
"""
import os
import re
from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr
import pytz

import importlib.util
from pathlib import Path

_kr_weekly_dc_path = Path(__file__).parent.parent / "kr_weekly" / "data_collector.py"
_spec = importlib.util.spec_from_file_location("kr_weekly_data_collector", _kr_weekly_dc_path)
_kr_weekly_dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_kr_weekly_dc)

_NAVER_HEADERS = _kr_weekly_dc._NAVER_HEADERS
get_top_stocks_weekly = _kr_weekly_dc.get_top_stocks_weekly

from shared.utils import fetch_with_retry

KST = pytz.timezone("Asia/Seoul")


def get_month_range() -> tuple[str, str, str, str]:
    """전월 1일~말일 날짜 계산 (매월 1일 실행 기준 — 지난달 결산).
    Returns: (month_start_YYYYMMDD, month_end_YYYYMMDD, month_start_display, month_end_display, month_label)
    """
    kst_now = datetime.now(KST)
    first_of_this_month = kst_now.replace(day=1)
    last_of_prev_month = first_of_this_month - timedelta(days=1)
    prev_month_start = last_of_prev_month.replace(day=1)
    return (
        prev_month_start.strftime("%Y%m%d"),
        last_of_prev_month.strftime("%Y%m%d"),
        prev_month_start.strftime("%Y-%m-%d"),
        last_of_prev_month.strftime("%Y-%m-%d"),
        f"{prev_month_start.year}년 {prev_month_start.month}월",
    )


def get_index_data_monthly(month_start_str: str, month_end_str: str) -> dict:
    """KOSPI/KOSDAQ 월간 등락률 — 전월 첫 거래일 종가 대비 마지막 거래일 종가."""
    result = {}
    start_dt = datetime.strptime(month_start_str, "%Y%m%d")
    end_dt = datetime.strptime(month_end_str, "%Y%m%d")
    for key, ticker in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            # 월초 이전 여유(직전월 말)를 살짝 포함해 첫 거래일을 놓치지 않게 조회
            fetch_start = (start_dt - timedelta(days=5)).strftime("%Y-%m-%d")
            fetch_end = end_dt.strftime("%Y-%m-%d")
            df = fdr.DataReader(ticker, fetch_start, fetch_end)
            df = df[df.index >= pd.Timestamp(start_dt)]
            if df.empty:
                result[key] = {}
                continue
            first_close = float(df["Close"].dropna().iloc[0])
            last_close = float(df["Close"].dropna().iloc[-1])
            pct = (last_close - first_close) / first_close * 100
            result[key] = {
                "close": round(last_close, 2),
                "month_start_close": round(first_close, 2),
                "monthly_pct": round(pct, 2),
            }
        except Exception as e:
            print(f"  [{key}] 월간 지수 수집 실패: {e}")
            result[key] = {}
    return result


def get_kospi_daily_pct_monthly(month_start_str: str, month_end_str: str) -> list:
    """이번 달 각 거래일의 KOSPI 전일 대비 등락률(%). [{date, pct}]"""
    try:
        start_dt = datetime.strptime(month_start_str, "%Y%m%d")
        end_dt = datetime.strptime(month_end_str, "%Y%m%d")
        fetch_start = (start_dt - timedelta(days=5)).strftime("%Y-%m-%d")
        fetch_end = end_dt.strftime("%Y-%m-%d")
        close = fdr.DataReader("KS11", fetch_start, fetch_end)["Close"].dropna()
        pct = close.pct_change() * 100
        out = []
        for idx, val in pct.items():
            if pd.notna(val) and idx >= pd.Timestamp(start_dt):
                out.append({"date": idx.strftime("%Y-%m-%d"), "pct": round(float(val), 2)})
        return out
    except Exception as e:
        print(f"  [코스피 일별등락] 월간 수집 실패: {e}")
        return []


def get_best_worst_days(daily_pct: list) -> dict:
    """월중 최고 상승일·최고 하락일."""
    if not daily_pct:
        return {"best_day": None, "worst_day": None}
    best = max(daily_pct, key=lambda x: x["pct"])
    worst = min(daily_pct, key=lambda x: x["pct"])
    return {"best_day": best, "worst_day": worst}


def get_investor_trend_monthly(month_end_str: str) -> dict:
    """월간 투자자별 순매수 합계 (kr_weekly의 일별 수급 함수를 재사용해 월초~월말 합산).

    kr_weekly.get_market_investor_trend_weekly는 요청 시점 기준 최근 거래일 목록을
    반환하는 방식이라, 월말 기준으로 한 번 호출하면 그 달 전체 거래일이 포함된다는
    보장이 없다(네이버 페이지가 보여주는 최근 거래일 수에 의존). 페이지를 여러 장
    조회해 월초~월말 범위를 채운다.
    """
    from bs4 import BeautifulSoup
    month_start = month_end_str[:6] + "01"
    all_rows = []
    try:
        for page in range(1, 4):  # 페이지당 약 20거래일 — 3페이지면 한 달 이상 커버
            resp = fetch_with_retry(
                "https://finance.naver.com/sise/investorDealTrendDay.naver",
                params={"bizdate": month_end_str, "sosok": "", "page": page},
                headers=_NAVER_HEADERS, timeout=10,
            )
            resp.encoding = "euc-kr"
            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", {"class": "type_1"})
            if not table:
                break

            def _num(td):
                raw = td.get_text(strip=True).replace(",", "")
                try:
                    return int(raw)
                except ValueError:
                    return None

            page_has_target_month = False
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 4:
                    continue
                date_text = tds[0].get_text(strip=True)
                if not re.match(r"^\d{2}\.\d{2}\.\d{2}$", date_text):
                    continue
                yy, mm, dd = date_text.split(".")
                date_full = f"20{yy}{mm}{dd}"
                if not (month_start <= date_full <= month_end_str):
                    if date_full < month_start:
                        continue
                    continue
                page_has_target_month = True
                individual, foreign, institution = _num(tds[1]), _num(tds[2]), _num(tds[3])
                if individual is None or foreign is None or institution is None:
                    continue
                all_rows.append({
                    "date": f"20{yy}-{mm}-{dd}",
                    "individual": individual * 100_000_000,
                    "foreign": foreign * 100_000_000,
                    "institution": institution * 100_000_000,
                })
            # 이 페이지에 목표 달 데이터가 전혀 없고 이미 그 이전 달까지 갔으면 중단
            if not page_has_target_month and all_rows:
                break
    except Exception as e:
        print(f"  [월간수급] 수집 실패: {e}")

    total = {
        "individual": sum(r["individual"] for r in all_rows),
        "foreign": sum(r["foreign"] for r in all_rows),
        "institution": sum(r["institution"] for r in all_rows),
        "days_count": len(all_rows),
    }
    return total


def get_news_monthly(month_label: str) -> list:
    """네이버 API로 월간 국내 증시 뉴스 수집."""
    client_id = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    queries = ["코스피 월간 결산", "코스피 이번달 증시"]
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
    print("[데이터 수집] 국내증시 월간 결산")

    month_start, month_end, month_start_display, month_end_display, month_label = get_month_range()
    print(f"  결산 대상: {month_label} ({month_start_display} ~ {month_end_display})")

    index_data = get_index_data_monthly(month_start, month_end)
    daily_pct = get_kospi_daily_pct_monthly(month_start, month_end)
    best_worst = get_best_worst_days(daily_pct)
    stock_data = get_top_stocks_weekly(month_end, month_start)  # 기간만 월 단위로 재사용
    investor_trend = get_investor_trend_monthly(month_end)
    news = get_news_monthly(month_label)

    return {
        "month_start": month_start_display,
        "month_end": month_end_display,
        "month_label": month_label,
        "kst_date": datetime.now(KST).strftime("%Y-%m-%d"),
        **index_data,
        "daily_pct_count": len(daily_pct),
        **best_worst,
        **stock_data,
        "investor_trend_monthly": investor_trend,
        "news": news,
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    data = collect_all()
    print(f"\n결산 대상: {data['month_label']}")
    kospi = data.get("kospi", {})
    print(f"KOSPI: {kospi.get('close')} (월간 {kospi.get('monthly_pct', 0):+.2f}%)")
    print(f"최고 상승일: {data.get('best_day')}")
    print(f"최고 하락일: {data.get('worst_day')}")
    print(f"뉴스: {len(data.get('news', []))}건")
