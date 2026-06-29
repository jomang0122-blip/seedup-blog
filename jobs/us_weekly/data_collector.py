# -*- coding: utf-8 -*-
"""
미국증시 위클리 데이터 수집
- 3대 지수 주간 등락률 (이전 금요일 종가 기준)
- 한국인 관심 종목 주간 등락률
- 주간 급등락 TOP3
- 주간 뉴스 헤드라인
"""
import yfinance as yf
import pytz
from datetime import datetime, timedelta

KST = pytz.timezone("Asia/Seoul")

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

NASDAQ_WATCH_LIST = [
    "AVGO", "COST", "NFLX", "AMD", "ADBE", "QCOM", "TXN", "ARM", "SMCI",
    "MU", "MRVL", "PANW", "AMAT", "LRCX", "INTC", "SNPS", "KLAC",
    "ASML", "MSTR", "COIN", "HOOD", "RIVN", "SOFI", "RBLX", "SNAP",
    "UBER", "LYFT", "ABNB", "DASH", "CRWD", "ZS", "NET", "DDOG",
]

INDEX_TICKERS = {
    "^DJI":  "다우존스",
    "^GSPC": "S&P 500",
    "^IXIC": "나스닥",
}


def _find_friday_closes(hist):
    """history DataFrame에서 금요일 종가만 추출. 최소 2개 필요."""
    fridays = hist[hist.index.dayofweek == 4]["Close"].dropna()
    return fridays


def _weekly_pct(hist):
    """이전 금요일 → 이번 금요일 등락률 계산."""
    fridays = _find_friday_closes(hist)
    if len(fridays) < 2:
        # 금요일 데이터가 부족하면 최근 2거래일로 대체
        series = hist["Close"].dropna()
        if len(series) < 2:
            return None
        return round((series.iloc[-1] - series.iloc[-2]) / series.iloc[-2] * 100, 2)
    return round((fridays.iloc[-1] - fridays.iloc[-2]) / fridays.iloc[-2] * 100, 2)


def _week_range_str(hist) -> tuple[str, str]:
    """이번 주 거래 첫날 ~ 마지막날 날짜 문자열 반환."""
    fridays = _find_friday_closes(hist)
    if len(fridays) >= 2:
        prev_fri = fridays.index[-2].strftime("%Y-%m-%d")
        this_fri = fridays.index[-1].strftime("%Y-%m-%d")
        return prev_fri, this_fri
    dates = hist.index.strftime("%Y-%m-%d")
    return dates[-5] if len(dates) >= 5 else dates[0], dates[-1]


def collect_indices() -> tuple[dict, str, str]:
    """3대 지수 주간 데이터. (indices_dict, week_start, week_end) 반환."""
    result = {}
    week_start, week_end = "", ""

    for ticker, name in INDEX_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="1mo")
            if hist.empty:
                continue
            pct = _weekly_pct(hist)
            close = round(hist["Close"].iloc[-1], 2)
            result[ticker] = {
                "name": name,
                "close": close,
                "weekly_pct": pct,
                "volume": int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0,
            }
            if not week_start:
                week_start, week_end = _week_range_str(hist)
        except Exception as e:
            print(f"  [경고] {ticker} 수집 실패: {e}")

    return result, week_start, week_end


def collect_fixed_stocks() -> dict:
    """한국인 관심 종목 주간 등락률."""
    result = {}
    for ticker, name in FIXED_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="1mo")
            if hist.empty:
                continue
            pct = _weekly_pct(hist)
            close = round(hist["Close"].iloc[-1], 2)
            result[ticker] = {
                "name": name,
                "close": close,
                "weekly_pct": pct if pct is not None else 0.0,
            }
        except Exception as e:
            print(f"  [경고] {ticker} 수집 실패: {e}")
    return result


def collect_top_movers(top_n: int = 3) -> list[dict]:
    """워치리스트 주간 급등락 TOP N."""
    try:
        raw = yf.download(NASDAQ_WATCH_LIST, period="1mo", progress=False, auto_adjust=True)
        if raw.empty:
            return []
        close = raw["Close"] if "Close" in raw.columns else raw.xs("Close", axis=1, level=0)

        changes = {}
        for ticker in NASDAQ_WATCH_LIST:
            if ticker not in close.columns:
                continue
            series = close[ticker].dropna()
            fridays = series[series.index.dayofweek == 4]
            if len(fridays) >= 2:
                pct = round((fridays.iloc[-1] - fridays.iloc[-2]) / fridays.iloc[-2] * 100, 2)
            elif len(series) >= 2:
                pct = round((series.iloc[-1] - series.iloc[-2]) / series.iloc[-2] * 100, 2)
            else:
                continue
            changes[ticker] = pct

        sorted_movers = sorted(changes.items(), key=lambda x: abs(x[1]), reverse=True)
        return [
            {"ticker": t, "weekly_pct": p, "direction": "up" if p >= 0 else "down"}
            for t, p in sorted_movers[:top_n]
        ]
    except Exception as e:
        print(f"  [경고] 주간 급등락 수집 실패: {e}")
        return []


def collect_news() -> list[str]:
    """Yahoo Finance 주간 뉴스 헤드라인 (최대 5건)."""
    for ticker in ["^IXIC", "SPY", "QQQ"]:
        try:
            news = yf.Ticker(ticker).news
            if not news:
                continue
            titles = []
            for item in news[:8]:
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
    print("  주간 지수 수집 중...")
    indices, week_start, week_end = collect_indices()

    if not indices:
        return {"market_closed": True}

    print(f"  주간 범위: {week_start} ~ {week_end}")
    print("  관심 종목 수집 중...")
    fixed_stocks = collect_fixed_stocks()

    print("  주간 급등락 탐색 중...")
    top_movers = collect_top_movers()

    print("  뉴스 수집 중...")
    news = collect_news()

    return {
        "market_closed": False,
        "week_start": week_start,
        "week_end": week_end,
        "kst_date": datetime.now(KST).strftime("%Y-%m-%d"),
        "indices": indices,
        "fixed_stocks": fixed_stocks,
        "top_movers": top_movers,
        "news": news,
    }


if __name__ == "__main__":
    data = collect_all()
    if data["market_closed"]:
        print("데이터 없음")
    else:
        print(f"\n주간: {data['week_start']} ~ {data['week_end']}")
        print("\n[3대 지수]")
        for t, v in data["indices"].items():
            print(f"  {v['name']}: {v['close']} (주간 {v['weekly_pct']:+.2f}%)")
        print("\n[관심 종목]")
        for t, v in data["fixed_stocks"].items():
            print(f"  {t} {v['name']}: ${v['close']} (주간 {v['weekly_pct']:+.2f}%)")
        print("\n[주간 급등락 TOP3]")
        for m in data["top_movers"]:
            print(f"  {m['ticker']}: {m['weekly_pct']:+.2f}%")
        print(f"\n[뉴스] {len(data['news'])}건")
