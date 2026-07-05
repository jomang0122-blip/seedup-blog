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
    "MU": "마이크론",
}

# 급등락 탐색용 워치리스트 (고정 풀 제외) — 한글명 매핑 (AI 환각 방지)
WATCH_NAMES = {
    "AVGO": "브로드컴",
    "COST": "코스트코",
    "NFLX": "넷플릭스",
    "AMD": "AMD",
    "ADBE": "어도비",
    "QCOM": "퀄컴",
    "TXN": "텍사스인스트루먼트",
    "ARM": "암홀딩스",
    "SMCI": "슈퍼마이크로",
    "MRVL": "마벨테크놀로지",
    "PANW": "팔로알토네트웍스",
    "AMAT": "어플라이드머티리얼즈",
    "LRCX": "램리서치",
    "INTC": "인텔",
    "SNPS": "시놉시스",
    "KLAC": "KLA",
    "ASML": "ASML",
    "MSTR": "스트래티지",
    "COIN": "코인베이스",
    "HOOD": "로빈후드",
    "RIVN": "리비안",
    "SOFI": "소파이",
    "RBLX": "로블록스",
    "SNAP": "스냅",
    "UBER": "우버",
    "LYFT": "리프트",
    "ABNB": "에어비앤비",
    "DASH": "도어대시",
    "CRWD": "크라우드스트라이크",
    "ZS": "지스케일러",
    "NET": "클라우드플레어",
    "DDOG": "데이터독",
}
NASDAQ_WATCH_LIST = list(WATCH_NAMES.keys())

INDEX_TICKERS = {
    "^DJI":  "다우존스",
    "^GSPC": "S&P 500",
    "^IXIC": "나스닥",
}


def _last_trading_close_per_week(series):
    """(ISO 연도, ISO 주차)로 그룹핑해 각 주의 마지막 거래일 종가만 추출.

    과거엔 "요일이 금요일(dayofweek==4)인 행"만 찾았는데, 금요일이 공휴일(예:
    미국 독립기념일 대체휴일, Juneteenth)이면 그 주엔 금요일 종가 행 자체가
    없어서 몇 주 전 금요일까지 건너뛰어버리는 사고가 있었다(실측: 2026-07-05
    발행에서 6/19·7/3 금요일이 둘 다 공휴일이라 "6월 12일~26일"로 2주를
    건너뜀). 요일로 찾지 않고 "그 주의 마지막 거래일"을 쓰면 금요일이
    휴장이어도 목요일 등 실제 마지막 거래일이 자동으로 그 주를 대표한다.
    """
    iso = series.index.isocalendar()
    grouped = series.groupby([iso["year"], iso["week"]])
    return grouped.tail(1)


def _weekly_pct(hist):
    """지난 주 마지막 거래일 → 이번 주 마지막 거래일 등락률 계산."""
    closes = _last_trading_close_per_week(hist["Close"].dropna())
    if len(closes) < 2:
        # 그래도 부족하면 최근 2거래일로 대체
        series = hist["Close"].dropna()
        if len(series) < 2:
            return None
        return round((series.iloc[-1] - series.iloc[-2]) / series.iloc[-2] * 100, 2)
    return round((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100, 2)


def _week_range_str(hist) -> tuple[str, str]:
    """이번 주 거래 첫날 ~ 마지막날 날짜 문자열 반환."""
    closes = _last_trading_close_per_week(hist["Close"].dropna())
    if len(closes) >= 2:
        prev_end = closes.index[-2].strftime("%Y-%m-%d")
        this_end = closes.index[-1].strftime("%Y-%m-%d")
        return prev_end, this_end
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
    """한국인 관심 종목 주간 등락률 (재시도 + N/A 행 유지)."""
    result = {}
    for ticker, name in FIXED_TICKERS.items():
        try:
            t = yf.Ticker(ticker)
            hist = None
            for period in ("1mo", "3mo"):
                h = t.history(period=period)
                if not h.empty:
                    hist = h
                    break

            if hist is None:
                print(f"  [경고] {ticker} 데이터 없음 — N/A 처리")
                result[ticker] = {"name": name, "close": None, "weekly_pct": None}
                continue

            pct = _weekly_pct(hist)
            close = round(hist["Close"].iloc[-1], 2)

            # 데이터 이상 필터: 주간 ±60% 초과는 분할 미조정 등 오류로 간주 → N/A
            if pct is not None and abs(pct) > 60:
                print(f"  [경고] {ticker} 주간 {pct:+.2f}% — 데이터 이상 의심, N/A 처리")
                close, pct = None, None

            if pct is None and close is not None:
                pct = 0.0
            result[ticker] = {"name": name, "close": close, "weekly_pct": pct}
        except Exception as e:
            print(f"  [경고] {ticker} 수집 실패: {e}")
            result[ticker] = {"name": name, "close": None, "weekly_pct": None}
    return result


_MOVER_NEWS_MIN_PCT = 3.0  # 이 등락률 미만이면 뉴스를 붙이지 않음(보합 종목에 억지 이유 금지)


def _mover_news(ticker: str) -> str:
    """급등락 종목의 실제 개별 뉴스 헤드라인 조회 — 지수 전체 뉴스에서
    티커 문자열을 억지로 매칭하지 않고, 해당 종목 전용 뉴스만 사용."""
    try:
        for item in (yf.Ticker(ticker).news or [])[:5]:
            if isinstance(item.get("content"), dict):
                title = item["content"].get("title", "")
            else:
                title = item.get("title", "")
            if title:
                return title[:120]
    except Exception:
        pass
    return ""


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
            week_closes = _last_trading_close_per_week(series)
            if len(week_closes) >= 2:
                pct = round((week_closes.iloc[-1] - week_closes.iloc[-2]) / week_closes.iloc[-2] * 100, 2)
            elif len(series) >= 2:
                pct = round((series.iloc[-1] - series.iloc[-2]) / series.iloc[-2] * 100, 2)
            else:
                continue
            # 데이터 이상 필터: 주간 ±60% 초과는 분할 미조정 등 오류로 간주
            if abs(pct) > 60:
                print(f"  [경고] {ticker} 주간 {pct:+.2f}% — 데이터 이상 의심, 급등락 제외")
                continue
            changes[ticker] = pct

        sorted_movers = sorted(changes.items(), key=lambda x: abs(x[1]), reverse=True)
        result = []
        for t, p in sorted_movers[:top_n]:
            last_close = round(float(close[t].dropna().iloc[-1]), 2) if t in close.columns else None
            news = _mover_news(t) if abs(p) >= _MOVER_NEWS_MIN_PCT else ""
            result.append({
                "ticker": t,
                "name": WATCH_NAMES.get(t, t),
                "close": last_close,
                "weekly_pct": p,
                "direction": "up" if p >= 0 else "down",
                "news": news,
            })
        return result
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
