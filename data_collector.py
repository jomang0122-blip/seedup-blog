# -*- coding: utf-8 -*-
import os
import re
import time
import requests
from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr
from bs4 import BeautifulSoup


# ── 공통 헤더 ─────────────────────────────────────────────────────────────

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


# ── 날짜 유틸 ─────────────────────────────────────────────────────────────

def get_latest_trading_date() -> str:
    """오늘 또는 가장 최근 거래일을 YYYYMMDD로 반환"""
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


# ── 지수 데이터 ───────────────────────────────────────────────────────────

def get_index_data(date_str: str) -> dict:
    """코스피/코스닥 종가, 등락률, 거래량"""
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    result = {}
    for key, ticker in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            df = fdr.DataReader(ticker, date_fmt, date_fmt)
            if df.empty:
                result[key] = {}
                continue
            row        = df.iloc[-1]
            close      = float(row["Close"])
            change_raw = float(row.get("Change", 0))
            change_pct = change_raw * 100
            prev_close = close / (1 + change_raw) if change_raw != -1 else close
            result[key] = {
                "close":      round(close, 2),
                "change":     round(close - prev_close, 2),
                "change_pct": round(change_pct, 2),
                "volume":     int(row.get("Volume", 0)),
            }
        except Exception as e:
            print(f"  [{key}] 지수 수집 실패: {e}")
            result[key] = {}
    return result


# ── 수급 데이터 (미구현 — 데이터 소스 없음) ───────────────────────────────

def get_investor_data(date_str: str) -> dict:
    """외국인/기관 순매수 (현재 외부 소스 미연결 — 빈 값 반환)"""
    return {"foreign_net": None, "institution_net": None}


# ── 종목 데이터 (FDR 시총 상위 샘플링) ────────────────────────────────────

def get_top_stocks(date_str: str) -> dict:
    """KOSPI 전체 종목 당일 등락률 — StockListing 단일 호출 (2초, 전종목)"""
    try:
        df = fdr.StockListing("KOSPI")

        # 등락률 컬럼 탐색 (FDR 오타: ChagesRatio)
        chg_col = next(
            (c for c in ["ChagesRatio", "ChangeRatio", "Change%", "Chg%"] if c in df.columns),
            None
        )
        if chg_col is None:
            raise ValueError(f"등락률 컬럼 없음. 컬럼 목록: {df.columns.tolist()}")

        df[chg_col] = pd.to_numeric(df[chg_col], errors="coerce")

        # 거래 없는 종목 제거 (상장폐지·거래정지)
        vol_col = next((c for c in ["Volume", "거래량"] if c in df.columns), None)
        if vol_col:
            df = df[pd.to_numeric(df[vol_col], errors="coerce") > 0]

        # 시총 1000억 미만 소형주 제거 (신뢰성 확보)
        if "Marcap" in df.columns:
            df = df[pd.to_numeric(df["Marcap"], errors="coerce") > 1_000_000_000_000]

        # 우선주 제거 (종목명이 '우', '우B', '우C'로 끝나는 종목)
        df = df[~df["Name"].astype(str).str.match(r".*우[BC]?$")]

        df = df.dropna(subset=[chg_col])
        total = len(df)

        gainers_df = df.nlargest(5, chg_col)
        losers_df  = df.nsmallest(5, chg_col)

        gainers = [{"name": str(r["Name"]), "change_pct": round(float(r[chg_col]), 2)}
                   for _, r in gainers_df.iterrows()]
        losers  = [{"name": str(r["Name"]), "change_pct": round(float(r[chg_col]), 2)}
                   for _, r in losers_df.iterrows()]

        print(f"  [종목] KOSPI 전체 {total}개 분석 완료")
        print(f"  [종목] 급등: {[g['name'] for g in gainers]}")
        print(f"  [종목] 급락: {[l['name'] for l in losers]}")
        return {"top_gainers": gainers, "top_losers": losers}

    except Exception as e:
        print(f"  [FDR 종목] 실패: {e}")
        return {"top_gainers": [], "top_losers": []}


# ── 섹터 데이터 (Naver Finance 메인 페이지) ─────────────────────────────────

def get_sector_data(date_str: str = None) -> dict:
    """코스피 업종별 등락률 TOP3 / BOTTOM3 (Naver Finance 스크래핑)"""
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
            a_tag   = cols[0].find("a")
            name    = a_tag.get_text(strip=True) if a_tag else cols[0].get_text(strip=True)
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

        if not sectors:
            return {"top_sectors": [], "bottom_sectors": []}

        sectors.sort(key=lambda x: x["change_pct"], reverse=True)
        print(f"  [섹터] {len(sectors)}개 업종 수집 완료")
        return {
            "top_sectors":    sectors[:3],
            "bottom_sectors": sectors[-3:][::-1],
        }
    except Exception as e:
        print(f"  [섹터] 수집 실패: {e}")
        return {"top_sectors": [], "bottom_sectors": []}


# ── 뉴스 ─────────────────────────────────────────────────────────────────

def _naver_news_search(query: str, display: int = 3) -> list:
    """네이버 검색 API 공통 호출 — 키 없으면 빈 리스트"""
    client_id     = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": query, "display": display, "sort": "date"},
            timeout=5,
        )
        items = resp.json().get("items", [])
        return [
            {
                "title":    re.sub(r"<[^>]+>", "", item["title"]),
                "link":     item.get("originallink") or item.get("link", ""),
                "pub_date": item.get("pubDate", ""),   # "Wed, 25 Jun 2026 15:30:00 +0900"
            }
            for item in items
        ]
    except Exception as e:
        print(f"  [뉴스] '{query}' 수집 실패: {e}")
        return []


def get_news(query: str = "코스피 증시 오늘") -> list:
    """시장 전체 뉴스 헤드라인 (제목만)"""
    items = _naver_news_search(query, display=5)
    return [i["title"] for i in items]


def _is_today(pub_date_str: str, today: str) -> bool:
    """pubDate 문자열("Wed, 25 Jun 2026 15:30:00 +0900")이 today(YYYYMMDD)와 같은 날인지 확인"""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_date_str)
        return dt.strftime("%Y%m%d") == today
    except Exception:
        return False


def get_stock_news(stock_names: list, max_per_stock: int = 2) -> dict:
    """종목별 당일 뉴스 — {'title': str, 'link': str} 형태로 반환.
    pubDate로 당일 기사 우선 선택, 없으면 최신순 fallback."""
    if not stock_names:
        return {}
    today = datetime.today().strftime("%Y%m%d")
    result = {}
    for name in stock_names:
        candidates = _naver_news_search(f"{name} 주가", display=10)
        # 1순위: 종목명 포함 + 당일 발행
        today_matched = [
            h for h in candidates
            if name in h["title"] and _is_today(h["pub_date"], today)
        ]
        if today_matched:
            result[name] = today_matched[:max_per_stock]
        else:
            # 2순위: 종목명 포함 (날짜 무관)
            matched = [h for h in candidates if name in h["title"]]
            result[name] = (matched or candidates)[:max_per_stock]
        time.sleep(0.1)
    matched_cnt = len([v for v in result.values() if v])
    today_cnt   = sum(1 for v in result.values() if v and _is_today(v[0]["pub_date"], today))
    print(f"  [종목뉴스] {matched_cnt}개 수집, 당일기사 {today_cnt}개")
    return result


# ── 통합 수집 ─────────────────────────────────────────────────────────────

def collect_all(date: str = None) -> dict:
    """전체 시황 데이터 수집"""
    if date is None:
        date = get_latest_trading_date()

    print(f"[데이터 수집] 날짜: {date}")

    index_data    = get_index_data(date)
    investor_data = get_investor_data(date)
    stock_result  = get_top_stocks(date)
    sector_data   = get_sector_data(date)
    news          = get_news()

    # 급등/급락 종목별 뉴스
    top_names = (
        [g["name"] for g in stock_result.get("top_gainers", [])] +
        [l["name"] for l in stock_result.get("top_losers",  [])]
    )
    stock_news = get_stock_news(top_names)

    return {
        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
        **index_data,
        **investor_data,
        **sector_data,
        **stock_result,
        "news":       news,
        "stock_news": stock_news,
    }


if __name__ == "__main__":
    import json
    data = collect_all()
    print("\n── 수집 결과 ──")
    print(json.dumps(data, ensure_ascii=False, indent=2))
