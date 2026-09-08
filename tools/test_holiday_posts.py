# -*- coding: utf-8 -*-
"""휴장 안내 발행 경로 사전 검증 — 실제 휴장일을 기다리지 않고 지금 확인한다.

왜 필요한가:
  휴장 안내 코드는 1년에 10여 번, 운영 기간으로 보면 두 달에 한 번꼴로만 실행된다.
  그래서 평소 발행으로는 절대 걸러지지 않고, 매번 실제 휴장일 당일에야 사고로 발견됐다.
    - 2026-07-17 제헌절: 영문 공휴일명이 그대로 발행됨 (총괄이 직접 수정)
    - 2026-08-17 광복절 대체휴일: "Alternative holiday for Liberation Day" 반환 → 발행 중단
    - 2026-09-07 노동절(미국): "S&P 500"의 &amp; 가 "amp"로 오검출 → 발행 중단
  전부 사후 발견이었고, 다음 휴장일까지 재발 여부를 확인할 방법이 없었다.
  이 스크립트는 그 경로를 강제로 실행해 위 사고들이 재발하지 않는지 즉시 확인한다.

실행:
    cd auto_publisher
    ./.venv/Scripts/python.exe tools/test_holiday_posts.py

주의: 실제 발행은 하지 않는다. 글 생성과 검사만 수행한다.
"""
import datetime as dt
import re
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ── 무거운 의존성 스텁 ──────────────────────────────────────────────
# 휴장 안내는 AI를 쓰지 않는 순수 파이썬 템플릿이라 ai_writer·data_collector가
# 필요 없다. 그런데 main.py가 모듈 최상단에서 이들을 임포트하므로, 그대로 두면
# anthropic·yfinance 같은 무거운 패키지까지 끌려와 실행이 매우 느려진다.
def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

_stub("anthropic", Anthropic=lambda *a, **k: None)
_stub("data_collector", collect_all=lambda *a, **k: {})
_stub("ai_writer", generate_post=lambda *a, **k: {},
      KR_DAILY_REQUIRED_SECTIONS=[], US_DAILY_REQUIRED_SECTIONS=[])

from shared.validator import assert_no_english_holiday_name  # noqa: E402

_HANGUL = re.compile(r"[가-힣]")
_ASCII_WORD = re.compile(r"[A-Za-z]{2,}")

results = []


def check(label: str, ok: bool, detail: str = ""):
    results.append((label, ok, detail))
    print(f"  {'✅' if ok else '❌'} {label}" + (f"  — {detail}" if detail else ""))


def _load(job: str):
    """jobs/<job>/main.py 를 임포트 (같은 폴더 내 상대 임포트를 위해 경로 추가)."""
    jobdir = REPO / "jobs" / job
    sys.path.insert(0, str(jobdir))
    import importlib
    mod = importlib.import_module("main")
    importlib.reload(mod)
    sys.path.remove(str(jobdir))
    return mod


def _holiday_weekdays(cal, years):
    """평일에 걸린 휴장일만 (주말은 어차피 발행 대상이 아님)."""
    out = []
    for y in years:
        for d in sorted(cal(y)):
            if d.weekday() < 5:
                out.append(d)
    return out


def test_kr(years):
    print(f"\n[국내증시] {years} 평일 휴장일 검증")
    import holidays as h
    kr = _load("kr_daily")
    days = _holiday_weekdays(lambda y: h.KR(years=y), years)
    # 근로자의 날·납회일은 holidays.KR에 없으므로 별도 추가
    for y in years:
        for extra in (dt.date(y, 5, 1), dt.date(y, 12, 31)):
            if extra.weekday() < 5 and extra not in days:
                days.append(extra)
    for d in sorted(days):
        name = kr._kr_holiday_name(d)
        check(f"{d} 휴장판정", kr.is_trading_day(d) is False)
        check(f"{d} 사유 한글 '{name}'",
              bool(_HANGUL.search(name)) and not _ASCII_WORD.search(name))
        try:
            post = kr.build_kr_holiday_post(d)
            assert_no_english_holiday_name(post["title"] + post["content"])
            check(f"{d} 안내글 생성·검사", True, post["title"])
        except Exception as e:
            check(f"{d} 안내글 생성·검사", False, f"{type(e).__name__}: {e}")


def test_us(years):
    print(f"\n[미국증시] {years} 평일 휴장일 검증")
    import holidays as h
    us = _load("us_daily")
    # 직전 거래일 요약 표 — S&P 500이 반드시 들어간다(2026-09-07 사고 지점)
    data = {"us_date": "2026-09-04", "indices": {
        "^DJI":  {"name": "다우존스", "close": 53414.25, "change_pct": -0.51},
        "^GSPC": {"name": "S&P 500", "close": 7718.60,  "change_pct": -0.38},
        "^IXIC": {"name": "나스닥",   "close": 26506.99, "change_pct": -0.29}}}
    for d in _holiday_weekdays(lambda y: h.financial_holidays("XNYS", years=y), years):
        name = us._holiday_name_kr(d)
        check(f"{d} 사유 한글 '{name}'",
              bool(_HANGUL.search(name)) and not _ASCII_WORD.search(name))
        try:
            post = us.build_holiday_post(data, [d])
            assert_no_english_holiday_name(post["title"] + post["content"])
            check(f"{d} 안내글 생성·검사", True, post["title"])
        except Exception as e:
            check(f"{d} 안내글 생성·검사", False, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    years = [2026, 2027]          # 내년치까지 미리 확인 — 매핑 누락 조기 발견
    test_kr(years)
    test_us(years)
    bad = [r for r in results if not r[1]]
    print("\n" + "=" * 60)
    print(f"총 {len(results)}건 검사 / 실패 {len(bad)}건")
    for label, _, detail in bad:
        print(f"  ❌ {label} — {detail}")
    sys.exit(1 if bad else 0)
