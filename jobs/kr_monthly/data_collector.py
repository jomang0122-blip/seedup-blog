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
    for key, ticker in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            # 전월 마지막 거래일 종가 — 전월 말일 이전 여유(공휴일·주말 대비 10일)
            prev_start = (prev_month_last_dt - timedelta(days=10)).strftime("%Y-%m-%d")
            prev_end = prev_month_last_dt.strftime("%Y-%m-%d")
            df_prev = fdr.DataReader(ticker, prev_start, prev_end)
            if df_prev.empty:
                result[key] = {}
                continue
            first_close = float(df_prev["Close"].dropna().iloc[-1])

            # 당월 마지막 거래일 종가
            df_cur = fdr.DataReader(ticker, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
            if df_cur.empty:
                result[key] = {}
                continue
            last_close = float(df_cur["Close"].dropna().iloc[-1])

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
    """
    try:
        start_dt = datetime.strptime(month_start_str, "%Y%m%d")
        end_dt = datetime.strptime(month_end_str, "%Y%m%d")
        fetch_start = (start_dt - timedelta(days=5)).strftime("%Y-%m-%d")
        fetch_end = end_dt.strftime("%Y-%m-%d")
        close = fdr.DataReader(ticker, fetch_start, fetch_end)["Close"].dropna()
        pct = close.pct_change() * 100
        out = []
        for idx, val in pct.items():
            if pd.notna(val) and idx >= pd.Timestamp(start_dt):
                out.append({"date": idx.strftime("%Y-%m-%d"), "pct": round(float(val), 2)})
        return out
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

    for key, ticker in [("kospi", "KS11"), ("kosdaq", "KQ11")]:
        try:
            df = fdr.DataReader(ticker, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
            if df.empty:
                continue
            close = df["Close"].dropna()
            hi_idx, lo_idx = close.idxmax(), close.idxmin()
            info = {
                "month_high": round(float(close.max()), 2),
                "month_high_date": hi_idx.strftime("%Y-%m-%d"),
                "month_low": round(float(close.min()), 2),
                "month_low_date": lo_idx.strftime("%Y-%m-%d"),
                "month_range_pct": round((float(close.max()) - float(close.min())) / float(close.min()) * 100, 2),
            }

            # 일평균 거래대금 (전월 대비) — FDR의 Amount 컬럼(원 단위)
            if "Amount" in df.columns:
                cur_amt = df["Amount"].dropna()
                if len(cur_amt):
                    info["avg_amount"] = float(cur_amt.mean())
                    df_prev = fdr.DataReader(
                        ticker,
                        prev_month_start.strftime("%Y-%m-%d"),
                        prev_month_last.strftime("%Y-%m-%d"),
                    )
                    prev_amt = df_prev["Amount"].dropna() if "Amount" in df_prev.columns else None
                    if prev_amt is not None and len(prev_amt):
                        info["prev_avg_amount"] = float(prev_amt.mean())
                        info["amount_change_pct"] = round(
                            (info["avg_amount"] - info["prev_avg_amount"]) / info["prev_avg_amount"] * 100, 2
                        )

            # 연초 대비 누적(YTD) — 전년도 마지막 거래일 종가 대비 이번 달 말 종가
            ytd_start = fdr.DataReader(
                ticker, f"{start_dt.year - 1}-12-15", f"{start_dt.year - 1}-12-31"
            )["Close"].dropna()
            if len(ytd_start):
                base = float(ytd_start.iloc[-1])
                info["ytd_pct"] = round((float(close.iloc[-1]) - base) / base * 100, 2)
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
        prev_last = start_dt - timedelta(days=1)
        prev = fdr.DataReader(
            "USD/KRW", (prev_last - timedelta(days=10)).strftime("%Y-%m-%d"), prev_last.strftime("%Y-%m-%d")
        )["Close"].dropna()
        cur = fdr.DataReader(
            "USD/KRW", start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
        )["Close"].dropna()
        if not len(prev) or not len(cur):
            return {}
        start_close, end_close = float(prev.iloc[-1]), float(cur.iloc[-1])
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
