# -*- coding: utf-8 -*-
"""
미국 시장 공통 상수·헬퍼 — us_daily·us_weekly 공용.

과거엔 종목 사전(FIXED_TICKERS·WATCH_NAMES)과 yfinance 뉴스 추출 로직이
두 job에 각각 복사돼 있어, 종목을 추가하면 한쪽만 반영되는 드리프트 위험이
있었다(2026-07-06 구조 진단에서 단일화). 종목 추가/제거는 이 파일만 수정.
"""
import yfinance as yf

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


def news_title(item: dict) -> str:
    """yfinance 뉴스 항목에서 제목 추출 — 버전별 구조(content dict/평면) 모두 대응."""
    if isinstance(item.get("content"), dict):
        return item["content"].get("title", "")
    return item.get("title", "")


def mover_news(ticker: str) -> str:
    """급등락 종목의 실제 개별 뉴스 헤드라인 조회 — 지수 전체 뉴스에서
    티커 문자열을 억지로 매칭하지 않고, 해당 종목 전용 뉴스만 사용."""
    try:
        for item in (yf.Ticker(ticker).news or [])[:5]:
            title = news_title(item)
            if title:
                return title[:120]
    except Exception:
        pass
    return ""


def collect_index_news(scan: int = 15, limit: int = 10) -> list:
    """Yahoo Finance 시장 뉴스 헤드라인 수집 (^IXIC → SPY → QQQ 순 폴백)."""
    for t in ["^IXIC", "SPY", "QQQ"]:
        try:
            news = yf.Ticker(t).news
            if not news:
                continue
            titles = [title for item in news[:scan] if (title := news_title(item))]
            if titles:
                return titles[:limit]
        except Exception:
            continue
    return []
