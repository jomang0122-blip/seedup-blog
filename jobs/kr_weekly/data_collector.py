# -*- coding: utf-8 -*-
"""
국내증시 위클리 데이터 수집
- KOSPI/KOSDAQ 주간 등락률 (이전 금요일 종가 기준)
- 외국인/기관/연기금 주간 수급 TOP3 (pykrx)
- 시가총액 상위 10종목 주간 등락 (FDR, 금요일 종가 비교)
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


_WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def get_market_investor_trend_weekly(this_fri_str: str) -> list:
    """네이버 investorDealTrendDay.naver — KOSPI 시장 전체 일별 개인/외국인/기관 순매수(원 단위).
    한 번의 요청으로 최근 여러 거래일치를 함께 반환 (일자별 개별 수집 불필요).
    """
    try:
        resp = fetch_with_retry(
            "https://finance.naver.com/sise/investorDealTrendDay.naver",
            params={"bizdate": this_fri_str, "sosok": "", "page": 1},
            headers=_NAVER_HEADERS, timeout=10,
        )
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", {"class": "type_1"})
        if not table:
            return []

        def _num(td):
            raw = td.get_text(strip=True).replace(",", "")
            try:
                return int(raw)
            except ValueError:
                return None

        rows = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            date_text = tds[0].get_text(strip=True)
            if not re.match(r"^\d{2}\.\d{2}\.\d{2}$", date_text):
                continue
            individual, foreign, institution = _num(tds[1]), _num(tds[2]), _num(tds[3])
            if individual is None or foreign is None or institution is None:
                continue
            yy, mm, dd = date_text.split(".")
            rows.append({
                "date":        f"20{yy}-{mm}-{dd}",
                "individual":  individual * 100_000_000,
                "foreign":     foreign * 100_000_000,
                "institution": institution * 100_000_000,
            })
        rows.sort(key=lambda r: r["date"])
        print(f"  [시장수급] {len(rows)}개 거래일: {[r['date'] for r in rows]}")
        return rows
    except Exception as e:
        print(f"  [시장수급] 수집 실패: {e}")
        return []


def get_kospi_daily_pct_weekly(this_fri_str: str, prev_fri_str: str) -> dict:
    """이번 주 각 거래일의 KOSPI 전일 대비 등락률(%). {YYYY-MM-DD: pct}

    이번 금요일(마지막 값) 종가는 FDR 반영지연 위험이 있어(실측 확인, 2026-07-03)
    네이버 모바일 API 실시간 값으로 교정 후 등락률을 재계산한다.
    """
    try:
        prev_fri_dt = datetime.strptime(prev_fri_str, "%Y%m%d")
        start = (prev_fri_dt - timedelta(days=3)).strftime("%Y-%m-%d")
        end   = datetime.strptime(this_fri_str, "%Y%m%d").strftime("%Y-%m-%d")
        close = fdr.DataReader("KS11", start, end)["Close"].dropna()

        try:
            resp = fetch_with_retry(
                "https://m.stock.naver.com/api/index/KOSPI/basic",
                headers=_NAVER_HEADERS, timeout=10,
            )
            live_close = float(resp.json().get("closePrice", "0").replace(",", ""))
            if live_close:
                close.iloc[-1] = live_close
        except Exception as e:
            print(f"  [코스피 종가교정] 실패(FDR 값 유지): {e}")

        pct = close.pct_change() * 100
        return {idx.strftime("%Y-%m-%d"): round(float(val), 2) for idx, val in pct.items() if pd.notna(val)}
    except Exception as e:
        print(f"  [코스피 일별등락] 수집 실패: {e}")
        return {}


def build_market_trend_weekly(this_fri_str: str, prev_fri_str: str) -> list:
    """일별 투자자 순매수 + 코스피 등락률 결합 — 이번 주(이전 금요일 초과 ~ 이번 금요일) 거래일만.
    [{date, weekday, individual, foreign, institution, kospi_pct}]
    """
    trend = get_market_investor_trend_weekly(this_fri_str)
    kospi_pct = get_kospi_daily_pct_weekly(this_fri_str, prev_fri_str)
    out = []
    for r in trend:
        if not (prev_fri_str < r["date"].replace("-", "") <= this_fri_str):
            continue
        d = datetime.strptime(r["date"], "%Y-%m-%d")
        out.append({
            **r,
            "weekday":   _WEEKDAY_KR[d.weekday()],
            "kospi_pct": kospi_pct.get(r["date"]),
        })
    return out


_TOP10_MARKETCAP_MIN = 10  # 시가총액 상위 몇 종목을 볼지


def get_top_stocks_weekly(this_fri_str: str, prev_fri_str: str) -> dict:
    """시가총액 상위 10종목의 주간(금~금) 등락률.

    과거 pykrx 기반 전체 시장 급등락 TOP5는 GitHub Actions에서 해외 IP 차단으로
    상시 실패(섹션이 매주 비어 있었음) + 소형 테마주 위주로 노출돼 정보 가치가 낮았음.
    kr_daily가 이미 검증한 FDR(FinanceDataReader) 기반으로 교체하고, 대상도
    시가총액 상위 10개 대형주로 한정 — 매주 안정적으로 채워지고 독자가 실제
    관심 있는 대형주 흐름만 보여준다.
    """
    try:
        df = fdr.StockListing("KOSPI")
        if "Marcap" not in df.columns:
            print(f"  [시총TOP10] Marcap 컬럼 없음: {df.columns.tolist()}")
            return {"top_gainers": [], "top_losers": []}

        df = df[~df["Name"].astype(str).str.match(r".*우[BC]?$")]  # 우선주 제외
        top10 = df.nlargest(_TOP10_MARKETCAP_MIN, "Marcap")

        prev_fri_dt = datetime.strptime(prev_fri_str, "%Y%m%d")
        this_fri_dt = datetime.strptime(this_fri_str, "%Y%m%d")
        start = (prev_fri_dt - timedelta(days=5)).strftime("%Y-%m-%d")
        end   = this_fri_dt.strftime("%Y-%m-%d")

        results = []
        for _, r in top10.iterrows():
            code = str(r["Code"]).zfill(6)
            name = str(r["Name"])
            try:
                hist = fdr.DataReader(code, start, end)["Close"].dropna()
                if hist.empty:
                    continue
                prev_close = this_close = None
                for idx, close in hist.items():
                    d = idx.strftime("%Y%m%d")
                    if d <= prev_fri_str:
                        prev_close = float(close)
                    if d <= this_fri_str:
                        this_close = float(close)
                if prev_close is None or this_close is None:
                    continue
                pct = round((this_close - prev_close) / prev_close * 100, 2)
                results.append({"name": name, "ticker": code, "change_pct": pct})
            except Exception as e:
                print(f"  [시총TOP10] {name} 수집 실패: {e}")
                continue

        gainers = sorted([r for r in results if r["change_pct"] >= 0], key=lambda x: x["change_pct"], reverse=True)
        losers  = sorted([r for r in results if r["change_pct"] < 0],  key=lambda x: x["change_pct"])
        print(f"  [시총TOP10 주간] {len(results)}종목 (상승 {len(gainers)} / 하락 {len(losers)})")
        return {"top_gainers": gainers, "top_losers": losers}

    except Exception as e:
        print(f"  [시총TOP10 주간] 수집 실패: {e}")
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
    market_trend  = build_market_trend_weekly(this_fri, prev_fri)
    stock_data    = get_top_stocks_weekly(this_fri, prev_fri)
    sector_data   = get_sector_data()
    news          = get_news_weekly()

    return {
        "week_start":    week_start,
        "week_end":      week_end,
        "this_fri":      this_fri,
        "kst_date":      datetime.now(KST).strftime("%Y-%m-%d"),
        **index_data,
        "market_trend":  market_trend,
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
