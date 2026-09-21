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

from shared.utils import (
    fetch_with_retry,
    fetch_naver_index_history,
    fetch_naver_index_amount,
    fetch_naver_fx_history,
    fetch_naver_investor_trend,
)

KST = pytz.timezone("Asia/Seoul")

# FDR 지수 데이터 중단(2026-09-08~)으로 지수·환율을 네이버로 교체하며 도입.
# 당월 + 전월을 함께 봐야 해서 45거래일, YTD는 전년 말까지 거슬러 올라간다.
_MONTH_LOOKBACK_DAYS = 45
_YTD_LOOKBACK_DAYS = 300
_TICKER_TO_INDEX = {"KS11": "KOSPI", "KQ11": "KOSDAQ"}


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
    """KOSPI/KOSDAQ 월간 등락률 — 전월 마지막 거래일 종가 대비 당월 마지막 거래일 종가.

    실사고(2026-07-27): 기존 코드는 df.index >= start_dt로 필터링해 "전월 말
    종가를 가져올 여유(fetch_start)"를 만들어놓고도 그 필터에서 다시 잘라내,
    실제로는 "당월 첫 거래일 대비 당월 마지막 거래일"(즉 당월 내 등락)을
    계산하고 있었다 — docstring이 말하는 "전월 말 대비"와 다른 값. kr_monthly
    최초 실행(테스트 목적 dry-run 미적용 실수로 라이브 발행됨) 때 KOSPI가
    실제로는 거의 보합(전월 말 대비 +0.00%)인데 -3.55%로, KOSDAQ은 실제
    -14.76%인데 -12.75%로 발행되는 사고로 이어짐. kr_weekly의
    get_index_data_weekly()와 동일하게 "기준일 이전 구간을 별도 조회해
    마지막 값을 쓰는" 패턴으로 수정.
    """
    result = {}
    start_dt = datetime.strptime(month_start_str, "%Y%m%d")
    end_dt = datetime.strptime(month_end_str, "%Y%m%d")
    prev_month_last_dt = start_dt - timedelta(days=1)
    prev_end_date = prev_month_last_dt.strftime("%Y-%m-%d")
    start_date, end_date = start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
    for key, index in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        try:
            # FDR 지수 데이터가 2026-09-08부터 멈춰 네이버로 교체
            # (shared/utils.fetch_naver_index_history() 참고)
            hist = fetch_naver_index_history(index, days=_MONTH_LOOKBACK_DAYS)

            # 전월 마지막 거래일 종가
            prev_rows = [h for h in hist if h["date"] <= prev_end_date]
            if not prev_rows:
                result[key] = {}
                continue
            first_close = prev_rows[-1]["close"]

            # 당월 마지막 거래일 종가
            cur_rows = [h for h in hist if start_date <= h["date"] <= end_date]
            if not cur_rows:
                result[key] = {}
                continue
            last_close = cur_rows[-1]["close"]

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


def get_kospi_daily_pct_monthly(month_start_str: str, month_end_str: str, ticker: str = "KS11") -> list:
    """이번 달 각 거래일의 지수 전일 대비 등락률(%). [{date, pct}]

    ticker 인자로 KOSPI(KS11)·KOSDAQ(KQ11)을 모두 지원한다 — 예전엔 KOSPI만
    조회해서 "월중 최고 상승일·하락일"이 코스피 기준 하나뿐이었는데, 총괄
    피드백(2026-09-01)으로 두 지수를 구분해 보여주도록 확장했다.

    2026-09-10: FDR 지수 중단으로 네이버로 교체. 등락률을 pct_change()로
    재계산하지 않고 네이버가 준 날짜별 값을 그대로 쓴다 — 날짜와 값이 한 행에
    묶여 있어 어긋날 수 없다(kr_weekly의 같은 계열 버그 재발 방지).
    ticker 인자는 호출부 호환을 위해 유지하고 내부에서 지수명으로 변환한다.
    """
    index = _TICKER_TO_INDEX.get(ticker, "KOSPI")
    try:
        start_date = datetime.strptime(month_start_str, "%Y%m%d").strftime("%Y-%m-%d")
        end_date = datetime.strptime(month_end_str, "%Y%m%d").strftime("%Y-%m-%d")
        return [
            {"date": h["date"], "pct": round(h["change_pct"], 2)}
            for h in fetch_naver_index_history(index, days=_MONTH_LOOKBACK_DAYS)
            if start_date <= h["date"] <= end_date
        ]
    except Exception as e:
        print(f"  [{ticker} 일별등락] 월간 수집 실패: {e}")
        return []


def get_index_extra_monthly(month_start_str: str, month_end_str: str) -> dict:
    """지수별 월중 고점·저점(종가 기준)과 날짜, 월간 변동폭, 일평균 거래대금(전월 대비),
    연초 대비 누적(YTD) 수익률 — 총괄 피드백(2026-09-01)으로 신설.

    "월간 +3.4%" 한 숫자만으로는 그 달에 지수가 어디까지 갔다 왔는지, 돈이 실제로
    들어왔는지(거래대금), 올해 전체에서 지금이 어디인지(YTD)를 알 수 없다.
    모두 FDR이 이미 반환하는 컬럼(Close/Amount)으로 계산 — 신규 외부 소스 없음.
    """
    out = {}
    start_dt = datetime.strptime(month_start_str, "%Y%m%d")
    end_dt = datetime.strptime(month_end_str, "%Y%m%d")
    prev_month_last = start_dt - timedelta(days=1)
    prev_month_start = prev_month_last.replace(day=1)

    start_date, end_date = start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
    prev_start_date = prev_month_start.strftime("%Y-%m-%d")
    prev_last_date = prev_month_last.strftime("%Y-%m-%d")
    ytd_cut = f"{start_dt.year - 1}-12-31"

    for key, index in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        try:
            # 연초 기준값까지 한 번에 받으려면 전년 말까지 거슬러 올라가야 한다
            # (네이버는 페이지당 60행 — fetch_naver_index_history가 페이징 처리)
            hist = fetch_naver_index_history(index, days=_YTD_LOOKBACK_DAYS)
            cur = [h for h in hist if start_date <= h["date"] <= end_date]
            if not cur:
                continue
            hi = max(cur, key=lambda h: h["close"])
            lo = min(cur, key=lambda h: h["close"])
            info = {
                "month_high": round(hi["close"], 2),
                "month_high_date": hi["date"],
                "month_low": round(lo["close"], 2),
                "month_low_date": lo["date"],
                "month_range_pct": round((hi["close"] - lo["close"]) / lo["close"] * 100, 2),
            }

            # 일평균 거래대금 (전월 대비) — 네이버 금융 일별 표(백만원 단위).
            # 지수 시세 JSON API에는 거래대금이 없어 이 지표만 별도 소스를 쓴다.
            amt = fetch_naver_index_amount(index, days=_MONTH_LOOKBACK_DAYS)
            cur_amt = [v for d, v in amt.items() if start_date <= d <= end_date]
            prev_amt = [v for d, v in amt.items() if prev_start_date <= d <= prev_last_date]
            if cur_amt:
                info["avg_amount"] = sum(cur_amt) / len(cur_amt)
                if prev_amt:
                    info["prev_avg_amount"] = sum(prev_amt) / len(prev_amt)
                    info["amount_change_pct"] = round(
                        (info["avg_amount"] - info["prev_avg_amount"]) / info["prev_avg_amount"] * 100, 2
                    )

            # 연초 대비 누적(YTD) — 전년도 마지막 거래일 종가 대비 이번 달 말 종가
            ytd_rows = [h for h in hist if h["date"] <= ytd_cut]
            if ytd_rows:
                base = ytd_rows[-1]["close"]
                info["ytd_pct"] = round((cur[-1]["close"] - base) / base * 100, 2)
                info["ytd_base_close"] = round(base, 2)

            out[key] = info
        except Exception as e:
            print(f"  [{key} 월간 부가지표] 수집 실패: {e}")
    return out


def get_fx_monthly(month_start_str: str, month_end_str: str) -> dict:
    """원달러 환율 월간 등락 — 국내증시 결산에서 외국인 수급과 직결되는 지표인데
    기존 리포트에 아예 없었다(총괄 피드백 2026-09-01로 신설)."""
    try:
        start_dt = datetime.strptime(month_start_str, "%Y%m%d")
        end_dt = datetime.strptime(month_end_str, "%Y%m%d")
        prev_last = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        # FDR의 USD/KRW가 2거래일 밀려 있어(2026-09-10 확인) 네이버로 교체.
        # 월말에 도는 job이라 마지막 날 환율이 빠지면 월간 등락률이 틀어진다.
        hist = fetch_naver_fx_history(days=_MONTH_LOOKBACK_DAYS)
        prev = [h for h in hist if h["date"] <= prev_last]
        cur = [h for h in hist
               if start_dt.strftime("%Y-%m-%d") <= h["date"] <= end_dt.strftime("%Y-%m-%d")]
        if not prev or not cur:
            return {}
        start_close, end_close = prev[-1]["close"], cur[-1]["close"]
        return {
            "start_close": round(start_close, 2),
            "close": round(end_close, 2),
            "monthly_pct": round((end_close - start_close) / start_close * 100, 2),
        }
    except Exception as e:
        print(f"  [환율] 월간 수집 실패: {e}")
        return {}


def get_best_worst_days(daily_pct: list) -> dict:
    """월중 최고 상승일·최고 하락일."""
    if not daily_pct:
        return {"best_day": None, "worst_day": None}
    best = max(daily_pct, key=lambda x: x["pct"])
    worst = min(daily_pct, key=lambda x: x["pct"])
    return {"best_day": best, "worst_day": worst}


def get_monthly_volatility(daily_pct: list) -> dict:
    """이번 달 KOSPI 일별 등락률의 변동성(표준편차) — 월간만이 보여줄 수 있는
    관점(blog-planning 회의 2026-07-27 1순위 채택). daily_pct는 이미
    get_kospi_daily_pct_monthly()가 만드는 값을 그대로 재사용 — 신규 데이터
    수집 불필요.
    """
    if not daily_pct or len(daily_pct) < 2:
        return {"volatility": None, "trading_days": len(daily_pct)}
    values = [d["pct"] for d in daily_pct]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = variance ** 0.5
    return {"volatility": round(std, 2), "trading_days": len(values)}


def get_prev_month_volatility(month_start_str: str) -> dict:
    """전월 KOSPI 일별 등락률 변동성 — 이번 달과 비교하기 위한 값.
    전월 범위를 별도로 계산해 get_kospi_daily_pct_monthly를 재사용한다.
    """
    start_dt = datetime.strptime(month_start_str, "%Y%m%d")
    prev_month_last = start_dt - timedelta(days=1)
    prev_month_start = prev_month_last.replace(day=1)
    prev_start_str = prev_month_start.strftime("%Y%m%d")
    prev_end_str = prev_month_last.strftime("%Y%m%d")
    try:
        prev_daily_pct = get_kospi_daily_pct_monthly(prev_start_str, prev_end_str)
        return get_monthly_volatility(prev_daily_pct)
    except Exception as e:
        print(f"  [전월 변동성] 수집 실패: {e}")
        return {"volatility": None, "trading_days": 0}


def get_investor_trend_monthly(month_start_str: str, month_end_str: str) -> dict:
    """월간 투자자별 순매수 합계 (하루씩 조회해 월초~월말 합산).

    ⚠️ 2026-09-19 실사고로 교체됨. 기존 desktop 페이지(finance.naver.com/sise/
    investorDealTrendDay.naver)가 HTTP 410 Gone으로 폐쇄됐다(kr_weekly가 같은
    함수를 쓰다 발행 중단까지 갔다). 거래일 목록은 지수 시세(이미 검증된
    fetch_naver_index_history)에서 구하고, 각 날짜의 수급은
    shared/utils.fetch_naver_investor_trend()로 받는다 — 새 모바일 API는
    desktop 페이지와 달리 날짜 하나당 값 하나만 주기 때문.

    한 달(약 20영업일)을 하루씩 조회해도 페이지당 6행씩 3-4페이지 넘기던
    기존 방식과 요청 수가 비슷하다.
    """
    try:
        trading_days = [
            h["date"].replace("-", "") for h in fetch_naver_index_history("KOSPI", days=_MONTH_LOOKBACK_DAYS)
            if month_start_str <= h["date"].replace("-", "") <= month_end_str
        ]
        rows = fetch_naver_investor_trend("KOSPI", trading_days)
    except Exception as e:
        print(f"  [월간수급] 수집 실패: {e}")
        rows = []

    total = {
        "individual": sum(r["individual"] for r in rows),
        "foreign": sum(r["foreign"] for r in rows),
        "institution": sum(r["institution"] for r in rows),
        "days_count": len(rows),
    }
    return total


def get_top10_rank_changes(month_start_str: str, month_end_str: str, top_n: int = 10) -> list:
    """시가총액 TOP10의 전월 말 대비 순위 변화 — 총괄 피드백(2026-09-01)으로 신설.

    시총 순위 히스토리를 주는 무료 소스가 없어서, 상장주식수가 한 달 사이 거의
    바뀌지 않는다는 전제로 역산한다: 주식수 = 현재시총 ÷ 현재종가 → 전월 말 시총
    = 주식수 × 전월 말 종가. 유상증자·액면분할처럼 주식수가 실제로 바뀐 종목은
    오차가 생길 수 있어, 순위 변화는 "참고용 근사치"로만 쓰고 등락률처럼 확정
    수치로 단정하지 않는다.

    후보를 TOP10이 아니라 TOP20으로 넓게 잡는 이유: 지난달 10위였다가 이번 달
    11위로 밀려난 종목이 있으면 그만큼 다른 종목의 순위가 올라간 것이므로,
    현재 TOP10만 봐서는 순위 변동을 정확히 계산할 수 없다.
    """
    from shared.utils import fetch_naver_market_listing
    try:
        start_dt = datetime.strptime(month_start_str, "%Y%m%d")
        prev_last = start_dt - timedelta(days=1)
        prev_start = (prev_last - timedelta(days=10)).strftime("%Y-%m-%d")
        prev_end = prev_last.strftime("%Y-%m-%d")

        df = fetch_naver_market_listing("KOSPI")
        df = df[~df["Name"].astype(str).str.match(r".*우[BC]?$")]  # 우선주 제외
        cand = df.nlargest(top_n * 2, "Marcap")

        rows = []
        for _, r in cand.iterrows():
            code = str(r["Code"]).zfill(6)
            try:
                prev_close = fdr.DataReader(code, prev_start, prev_end)["Close"].dropna()
                if not len(prev_close):
                    continue
                cur_close = fdr.DataReader(code, start_dt.strftime("%Y-%m-%d"),
                                           datetime.strptime(month_end_str, "%Y%m%d").strftime("%Y-%m-%d"))["Close"].dropna()
                if not len(cur_close):
                    continue
                shares = float(r["Marcap"]) / float(cur_close.iloc[-1])
                rows.append({
                    "name": str(r["Name"]), "ticker": code,
                    "cur_marcap": float(r["Marcap"]),
                    "prev_marcap": shares * float(prev_close.iloc[-1]),
                })
            except Exception:
                continue

        cur_ranked = sorted(rows, key=lambda x: x["cur_marcap"], reverse=True)
        prev_ranked = sorted(rows, key=lambda x: x["prev_marcap"], reverse=True)
        prev_rank_map = {r["ticker"]: i + 1 for i, r in enumerate(prev_ranked)}

        out = []
        for i, r in enumerate(cur_ranked[:top_n]):
            prev_rank = prev_rank_map.get(r["ticker"])
            out.append({
                "name": r["name"], "ticker": r["ticker"],
                "rank": i + 1, "prev_rank": prev_rank,
                "rank_change": (prev_rank - (i + 1)) if prev_rank else None,
            })
        return out
    except Exception as e:
        print(f"  [시총 순위변화] 수집 실패: {e}")
        return []


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
    daily_pct_kq = get_kospi_daily_pct_monthly(month_start, month_end, ticker="KQ11")
    best_worst = get_best_worst_days(daily_pct)
    best_worst_kq = get_best_worst_days(daily_pct_kq)
    volatility = get_monthly_volatility(daily_pct)
    prev_volatility = get_prev_month_volatility(month_start)
    index_extra = get_index_extra_monthly(month_start, month_end)
    fx = get_fx_monthly(month_start, month_end)
    stock_data = get_top_stocks_weekly(month_end, month_start)  # 기간만 월 단위로 재사용
    rank_changes = get_top10_rank_changes(month_start, month_end)
    investor_trend = get_investor_trend_monthly(month_start, month_end)
    news = get_news_monthly(month_label)

    return {
        "month_start": month_start_display,
        "month_end": month_end_display,
        "month_label": month_label,
        "kst_date": datetime.now(KST).strftime("%Y-%m-%d"),
        **index_data,
        "daily_pct_count": len(daily_pct),
        **best_worst,
        "best_worst_kosdaq": best_worst_kq,
        "volatility": volatility,
        "prev_volatility": prev_volatility,
        "index_extra": index_extra,
        "fx": fx,
        "rank_changes": rank_changes,
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
