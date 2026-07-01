# -*- coding: utf-8 -*-
import os
import requests
import yfinance as yf
import pytz
from datetime import datetime

KST = pytz.timezone("Asia/Seoul")

# 한국인 관심 고정 풀 (항상 수집)
FIXED_TICKERS = {
    "NVDA": "엔비디아",
    "TSLA": "테슬라",
    "SPCX": "스페이스엑스",
    "IONQ": "아이온큐",
    "AAPL": "애플",
    "GOOGL": "알파벳(구글)",
    "MSFT": "마이크로소프트",
    "META": "메타",
    "AMZN": "아마존",
    "PLTR": "팔란티어",
}

# 급등락 TOP 3 탐색용 워치리스트 (고정 풀 제외)
NASDAQ_WATCH_LIST = [
    "AVGO", "COST", "NFLX", "AMD", "ADBE", "QCOM", "TXN", "ARM", "SMCI",
    "MU", "MRVL", "PANW", "AMAT", "LRCX", "INTC", "SNPS", "KLAC",
    "ASML", "MSTR", "COIN", "HOOD", "RIVN", "SOFI", "RBLX", "SNAP",
    "UBER", "LYFT", "ABNB", "DASH", "CRWD", "ZS", "NET", "DDOG",
]

INDEX_TICKERS = {
    "^DJI": "다우존스",
    "^GSPC": "S&P 500",
    "^IXIC": "나스닥",
}


def _pct_change(hist) -> float | None:
    """history DataFrame에서 전일 대비 등락률 계산"""
    series = hist["Close"].dropna()
    if len(series) >= 2:
        return round((series.iloc[-1] - series.iloc[-2]) / series.iloc[-2] * 100, 2)
    return None


def collect_indices() -> tuple[dict, str]:
    """3대 지수 수집. (indices_dict, us_trading_date_str) 반환"""
    result = {}
    us_date = ""

    for ticker, name in INDEX_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty:
                continue
            close = round(hist["Close"].iloc[-1], 2)
            pct = _pct_change(hist)
            volume = int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0
            result[ticker] = {
                "name": name,
                "close": close,
                "change_pct": pct,
                "volume": volume,
            }
            if not us_date and not hist.empty:
                us_date = hist.index[-1].strftime("%Y-%m-%d")
        except Exception as e:
            print(f"  [경고] {ticker} 수집 실패: {e}")

    return result, us_date


def collect_fixed_stocks() -> dict:
    """고정 풀 종목 개별 수집"""
    result = {}
    for ticker, name in FIXED_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if hist.empty:
                continue
            close = round(hist["Close"].iloc[-1], 2)
            pct = _pct_change(hist)
            result[ticker] = {
                "name": name,
                "close": close,
                "change_pct": pct if pct is not None else 0.0,
            }
        except Exception as e:
            print(f"  [경고] {ticker} 수집 실패: {e}")

    return result


def collect_top_movers(top_n: int = 3) -> list[dict]:
    """워치리스트에서 당일 급등락 상위 top_n종목 (절댓값 기준)"""
    try:
        raw = yf.download(
            NASDAQ_WATCH_LIST,
            period="5d",
            progress=False,
            auto_adjust=True,
        )
        if raw.empty:
            return []

        close = raw["Close"] if "Close" in raw.columns else raw.xs("Close", axis=1, level=0)

        changes = {}
        for ticker in NASDAQ_WATCH_LIST:
            if ticker not in close.columns:
                continue
            series = close[ticker].dropna()
            if len(series) < 2:
                continue
            pct = round((series.iloc[-1] - series.iloc[-2]) / series.iloc[-2] * 100, 2)
            changes[ticker] = pct

        sorted_movers = sorted(changes.items(), key=lambda x: abs(x[1]), reverse=True)
        result = []
        for ticker, pct in sorted_movers[:top_n]:
            result.append({
                "ticker": ticker,
                "change_pct": pct,
                "direction": "up" if pct >= 0 else "down",
            })
        return result

    except Exception as e:
        print(f"  [경고] 급등락 종목 수집 실패: {e}")
        return []


def collect_economic_calendar(us_date: str) -> list[dict]:
    """finnhub 경제 캘린더에서 당일 발표된 미국 경제 지표 수집."""
    token = os.getenv("FINNHUB_API_KEY", "")
    if not token:
        print("  [경고] FINNHUB_API_KEY 없음 — 경제 지표 수집 생략")
        return []
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": us_date, "to": us_date, "token": token},
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json().get("economicCalendar", [])
        us_events = [e for e in events if e.get("country", "") == "US"]
        result = []
        for e in us_events[:6]:
            result.append({
                "event": e.get("event", ""),
                "actual": e.get("actual"),
                "estimate": e.get("estimate"),
                "unit": e.get("unit", ""),
            })
        print(f"  [경제지표] {len(result)}건 수집")
        return result
    except Exception as exc:
        print(f"  [경고] 경제 지표 수집 실패: {exc}")
        return []


def collect_news() -> list[str]:
    """Yahoo Finance 뉴스 헤드라인 수집 (최대 5건)"""
    tickers_to_try = ["^IXIC", "SPY", "QQQ"]
    for t in tickers_to_try:
        try:
            ticker = yf.Ticker(t)
            news = ticker.news
            if not news:
                continue
            titles = []
            for item in news[:8]:
                # yfinance 버전별 구조 대응
                if isinstance(item.get("content"), dict):
                    title = item["content"].get("title", "")
                else:
                    title = item.get("title", "")
                if title:
                    titles.append(title)
            if titles:
                return titles[:5]
        except Exception:
            continue
    return []


def collect_all() -> dict:
    """전체 데이터 수집 통합 함수"""
    print("  지수 수집 중...")
    indices, us_date = collect_indices()

    if not indices:
        return {"market_closed": True}

    print(f"  미국 거래일: {us_date}")
    print("  고정 풀 종목 수집 중...")
    fixed_stocks = collect_fixed_stocks()

    print("  급등락 종목 탐색 중...")
    top_movers = collect_top_movers()

    print("  뉴스 수집 중...")
    news = collect_news()

    print("  경제 지표 수집 중...")
    economic_calendar = collect_economic_calendar(us_date)

    kst_date = datetime.now(KST).strftime("%Y-%m-%d")

    return {
        "market_closed": False,
        "us_date": us_date,
        "kst_date": kst_date,
        "indices": indices,
        "fixed_stocks": fixed_stocks,
        "top_movers": top_movers,
        "news": news,
        "economic_calendar": economic_calendar,
    }


if __name__ == "__main__":
    data = collect_all()
    if data["market_closed"]:
        print("휴장일")
    else:
        print(f"\n미국 거래일: {data['us_date']}")
        print("\n[3대 지수]")
        for t, v in data["indices"].items():
            print(f"  {v['name']}: {v['close']} ({v['change_pct']:+.2f}%)")
        print("\n[고정 풀]")
        for t, v in data["fixed_stocks"].items():
            print(f"  {t} {v['name']}: ${v['close']} ({v['change_pct']:+.2f}%)")
        print("\n[급등락 TOP 3]")
        for m in data["top_movers"]:
            print(f"  {m['ticker']}: {m['change_pct']:+.2f}%")
        print(f"\n[뉴스] {len(data['news'])}건")
        for n in data["news"]:
            print(f"  - {n}")
