# -*- coding: utf-8 -*-
"""get_latest_trading_date() 검증 — 발행 날짜가 실제 거래일과 맞는지 확인한다.

실행:
    cd auto_publisher
    ./.venv/Scripts/python.exe tools/test_trading_date.py


FinanceDataReader는 임포트가 매우 느리고(구글 드라이브 동기화 venv) 이번 수정의
정상 경로에서는 쓰이지도 않으므로 스텁으로 대체한다. 폴백 경로 검증에는
스텁이 오히려 유리하다 — FDR이 죽은 상황(현재 상태)을 그대로 흉내낼 수 있다.
"""
import sys
import types
import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "jobs" / "kr_daily"))


class _FakeDF:
    def __init__(self, empty): self.empty = empty


def _make_fdr(last_date):
    """FDR 흉내 — last_date 이하의 평일에만 데이터가 있다고 응답."""
    m = types.ModuleType("FinanceDataReader")
    def DataReader(code, start, end=None):
        d = dt.date.fromisoformat(start)
        has = (last_date is not None) and d <= last_date and d.weekday() < 5
        return _FakeDF(empty=not has)
    m.DataReader = DataReader
    return m


# 현재 FDR 실제 상태(2026-09-07에서 멈춤)를 그대로 재현
sys.modules["FinanceDataReader"] = _make_fdr(dt.date(2026, 9, 7))

import data_collector as dc  # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"  {'OK ' if ok else 'NG '} {label}" + (f" — {detail}" if detail else ""))


print("[1] 정상 경로 — 네이버에서 거래일을 받아온다")
got = dc.get_latest_trading_date()
print(f"    반환값: {got}")
check("YYYYMMDD 8자리", len(got) == 8 and got.isdigit(), got)

# 네이버가 주는 최신 거래일과 직접 대조
import json, urllib.request  # noqa: E402
req = urllib.request.Request(
    "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=3&page=1",
    headers={"User-Agent": "Mozilla/5.0"})
rows = json.load(urllib.request.urlopen(req, timeout=20))
expect = rows[0]["localTradedAt"].replace("-", "")
check("네이버 최신 거래일과 일치", got == expect, f"기대 {expect}")

# FDR이 멈춘 날짜(20260907)를 그대로 쓰지 않는지 — 이번 사고의 핵심
check("FDR이 멈춘 20260907을 쓰지 않음", got != "20260907", f"반환 {got}")

print("\n[2] 폴백 경로 — 네이버가 죽었을 때 FDR로 넘어간다")
orig = dc.fetch_with_retry
dc.fetch_with_retry = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("네이버 접속 실패(모의)"))
try:
    fb = dc.get_latest_trading_date()
    print(f"    반환값: {fb}")
    check("폴백이 값을 반환", len(fb) == 8 and fb.isdigit(), fb)
    check("폴백은 FDR의 마지막 날짜(20260907)", fb == "20260907", fb)
finally:
    dc.fetch_with_retry = orig

print("\n[3] 네이버·FDR 둘 다 죽으면 예외를 던진다")
dc.fetch_with_retry = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("네이버 접속 실패(모의)"))
sys.modules["FinanceDataReader"] = _make_fdr(None)
dc.fdr = sys.modules["FinanceDataReader"]
try:
    dc.get_latest_trading_date()
    check("RuntimeError 발생", False, "예외가 안 났음")
except RuntimeError as e:
    check("RuntimeError 발생", True, str(e))
finally:
    dc.fetch_with_retry = orig

print("\n" + "=" * 55)
bad = results.count(False)
print(f"총 {len(results)}건 / 실패 {bad}건")
sys.exit(1 if bad else 0)
