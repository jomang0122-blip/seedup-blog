# -*- coding: utf-8 -*-
"""투자자별 매매동향(개인/외국인/기관) 데이터 소스 검증.

왜 필요한가:
  기존 desktop 페이지(finance.naver.com/sise/investorDealTrendDay.naver)가
  2026-09-19 HTTP 410 Gone으로 완전히 폐쇄됐다. kr_weekly가 이 데이터 없이는
  필수 섹션 구조 검증을 통과할 수 없어 3회 재생성 끝에 발행이 중단됐다
  (크레딧 3배 소모, kr_weekly_20260919 실행 로그 참고).

  shared/utils.fetch_naver_investor_trend()로 교체했고, kr_weekly·kr_monthly
  둘 다 이 함수를 쓴다. 이 스크립트는 새 소스가 실제로 채워지는지, 그리고
  지난주 이미 발행된 표의 값과 정확히 일치하는지 확인한다.

실행:
    cd auto_publisher
    python tools/test_investor_trend.py

  시스템 파이썬 권장 — 이 경로는 FDR을 쓰지 않으므로 느린 드라이브 동기화
  venv를 거칠 필요가 없다.

주의: 실제 발행은 하지 않는다. 조회와 대조만 수행한다.
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# FinanceDataReader 스텁 — 이 경로는 FDR을 쓰지 않아야 한다. 실수로 부르면
# 즉시 예외로 드러난다.
if "FinanceDataReader" not in sys.modules:
    _stub = types.ModuleType("FinanceDataReader")
    _stub.DataReader = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("테스트 스텁 — 수급 경로는 FDR을 쓰지 않아야 한다"))
    _stub.StockListing = lambda *a, **k: None
    sys.modules["FinanceDataReader"] = _stub

from shared.utils import fetch_naver_investor_trend  # noqa: E402

results = []


def check(label: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(f"  {'OK ' if ok else 'NG '} {label}" + (f" — {detail}" if detail else ""))


print("[1] 죽은 구간(2026-09-19 사고 당시) 재조회 — 이제 채워져야 한다")
fail_dates = ["20260915", "20260916", "20260917", "20260918"]
rows = fetch_naver_investor_trend("KOSPI", fail_dates)
check("4개 날짜 전부 채워짐", len(rows) == len(fail_dates), f"{len(rows)}건")
check("과거→최신 정렬", rows == sorted(rows, key=lambda r: r["date"]))

print("\n[2] 이미 발행된 표(9/9 국내증시 위클리)와 값 대조")
# 9/9 발행글 표에 실린 값(억원): 9/7 개인 -68374·외국인 +25532·기관 +26491,
# 9/11 개인 +18675·외국인 -22984·기관 -12184
known = {"20260907": (-68374, 25532, 26491), "20260911": (18675, -22984, -12184)}
rows2 = fetch_naver_investor_trend("KOSPI", list(known.keys()))
mismatch = []
for r in rows2:
    d = r["date"].replace("-", "")
    exp = known[d]
    got = (r["individual"] // 100_000_000, r["foreign"] // 100_000_000, r["institution"] // 100_000_000)
    if got != exp:
        mismatch.append((d, exp, got))
check("발행 표 값과 완전 일치", len(rows2) == 2 and not mismatch,
      str(mismatch) if mismatch else "2건 모두 일치")

print("\n[3] KOSDAQ도 동작하는지")
rows3 = fetch_naver_investor_trend("KOSDAQ", ["20260918"])
check("KOSDAQ 조회됨", bool(rows3), str(rows3))

print("\n[4] kr_weekly.get_market_investor_trend_weekly — 지난주 실패 구간 재현")
sys.path.insert(0, str(REPO / "jobs" / "kr_weekly"))
import data_collector as wk  # noqa: E402

this_fri, prev_fri = "20260918", "20260911"
trend = wk.get_market_investor_trend_weekly(this_fri, prev_fri)
check("5거래일 전부 채워짐(9/19 실패 구간)", len(trend) == 5, f"{len(trend)}건")

full = wk.build_market_trend_weekly(this_fri, prev_fri)
check("build_market_trend_weekly 결합까지 정상",
      len(full) == 5 and all(r["kospi_pct"] is not None for r in full))

print("\n[5] kr_monthly.get_investor_trend_monthly — 지난달(8월) 합계")
# kr_weekly·kr_monthly 둘 다 모듈명이 "data_collector"라 캐시가 겹친다 —
# 지우고 다시 임포트해야 kr_monthly 쪽이 실제로 로드된다.
del sys.modules["data_collector"]
sys.path.insert(0, str(REPO / "jobs" / "kr_monthly"))
import data_collector as mo  # noqa: E402

monthly = mo.get_investor_trend_monthly("20260801", "20260831")
check("8월 한 달 20거래일 안팎 확보", monthly["days_count"] >= 15, str(monthly))

print("\n" + "=" * 58)
bad = results.count(False)
print(f"총 {len(results)}건 검사 / 실패 {bad}건")
sys.exit(1 if bad else 0)
