# -*- coding: utf-8 -*-
"""필수 섹션 목록과 데이터 가용성이 어긋나지 않는지 4개 job 전수 검증.

왜 필요한가:
  2026-09-19 국내증시 위클리 실사고: 투자자별 매매동향 데이터 소스가 죽자
  본문 생성 프롬프트는 "데이터 없으면 그 섹션 통째로 삭제"를 지시하는데,
  검증기(assert_structure_complete)는 정적 REQUIRED_SECTIONS 목록으로 그
  섹션을 여전히 필수로 요구했다. 절대 채워질 수 없는 섹션을 두고 3회
  재생성이 반복된 끝에 발행이 중단됐다(크레딧 3배 소모).

  전수조사 결과 같은 패턴이 kr_daily(특징주)·us_daily(핵심 뉴스)·
  us_weekly(급등락 TOP3·핵심 뉴스)에도 잠복해 있었다 — 아직 안 터졌을
  뿐 데이터 소스 하나만 죽으면 언제든 재발할 구조였다.

  근본 수정: 각 ai_writer.py에 required_sections_for(data)를 추가해
  "이 데이터로 실제 채울 수 있는 섹션만" 반환하게 하고, main.py는 정적
  상수 대신 이 반환값으로 검증한다. 데이터와 요구사항이 같은 함수에서
  나오므로 구조적으로 어긋날 수 없다.

  이 스크립트는 Anthropic API를 호출하지 않는다(크레딧 0) — 순수 로직
  (required_sections_for·assert_structure_complete)만 검증한다. 각 job의
  실패 시나리오를 "정적 목록으로는 여전히 실패 재현" + "동적 목록으로는
  통과" + "진짜 잘림은 여전히 잡힘" 3단계로 확인한다.

실행:
    cd auto_publisher
    python tools/test_required_sections.py

주의: 실제 발행은 하지 않고 AI도 호출하지 않는다.
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

# anthropic 클라이언트 생성 자체를 막아둔다 — 이 테스트가 실수로 API를
# 부르면 즉시 여기서 죽어야 한다(크레딧 보호). 각 ai_writer.py 모듈
# 최상단이 `client = Anthropic()`을 실행하므로 인스턴스화까지 스텁해야 한다.
class _NoCallClient:
    def __init__(self, *a, **k):
        pass

    class messages:
        @staticmethod
        def create(*a, **k):
            raise RuntimeError("테스트에서 API를 호출하려 함 — 금지된 경로")


_anthropic_stub = types.ModuleType("anthropic")
_anthropic_stub.Anthropic = _NoCallClient
sys.modules["anthropic"] = _anthropic_stub

from shared.validator import assert_structure_complete  # noqa: E402

results = []


def check(label: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(f"  {'OK ' if ok else 'NG '} {label}" + (f" — {detail}" if detail else ""))


def _import_ai_writer(job: str):
    """job마다 모듈명이 겹치므로(ai_writer·data_collector) 매번 캐시를 지우고 새로 임포트."""
    import importlib
    for name in ("ai_writer",):
        sys.modules.pop(name, None)
    jobdir = REPO / "jobs" / job
    sys.path.insert(0, str(jobdir))
    try:
        mod = importlib.import_module("ai_writer")
    finally:
        sys.path.remove(str(jobdir))
    return mod


def _reproduce(job_label: str, aw, empty_data: dict, full_data: dict,
               fake_content_missing: str, static_list_name: str):
    """9/19 사고를 그대로 재현: (A) 정적 목록은 실패 (B) 동적 목록은 통과
    (C) 데이터가 있는데 섹션이 없으면(진짜 잘림) 여전히 잡힘."""
    static_list = getattr(aw, static_list_name)
    dyn_empty = aw.required_sections_for(empty_data)
    dyn_full = aw.required_sections_for(full_data)

    try:
        assert_structure_complete(fake_content_missing, static_list, job_label)
        check(f"[{job_label}] (A) 정적 목록 → 사고 재현(실패해야 정상)", False, "실패해야 하는데 통과함")
    except ValueError:
        check(f"[{job_label}] (A) 정적 목록 → 사고 재현(실패해야 정상)", True)

    try:
        assert_structure_complete(fake_content_missing, dyn_empty, job_label)
        check(f"[{job_label}] (B) 동적 목록 → 발행 중단 해소(통과해야 정상)", True)
    except ValueError as e:
        check(f"[{job_label}] (B) 동적 목록 → 발행 중단 해소(통과해야 정상)", False, str(e))

    try:
        assert_structure_complete(fake_content_missing, dyn_full, job_label)
        check(f"[{job_label}] (C) 진짜 잘림은 여전히 잡힘(실패해야 정상)", False, "실패해야 하는데 통과함")
    except ValueError:
        check(f"[{job_label}] (C) 진짜 잘림은 여전히 잡힘(실패해야 정상)", True)


print("=" * 15, "kr_weekly", "=" * 15)
aw = _import_ai_writer("kr_weekly")
empty = {"market_trend": [], "top_gainers": [], "top_losers": []}
full = {"market_trend": [{"date": "2026-09-18"}], "top_gainers": [{"name": "x"}], "top_losers": []}
fake = """
## 이번 주 핵심 요약
### 📊 주간 시장 지표
### 🏭 당일 주도·약세 섹터
### 📰 이번 주 핵심 뉴스
### 💬 이번 주를 돌아보며
### 🔮 다음 주 전망
"""
_reproduce("국내증시 위클리", aw, empty, full, fake, "KR_WEEKLY_REQUIRED_SECTIONS")

print("\n" + "=" * 15, "kr_daily", "=" * 15)
aw = _import_ai_writer("kr_daily")
empty = {"top_gainers": [], "top_losers": []}
full = {"top_gainers": [{"name": "삼성전자"}], "top_losers": []}
fake = """
### 📊 1. 시장 지표 종합
국내 증시 마감 지수
### 당일 주도 섹터 및 테마
### 🔮 3. 다음 거래일 전망
"""
_reproduce("국내증시 데일리", aw, empty, full, fake, "KR_DAILY_REQUIRED_SECTIONS")

print("\n" + "=" * 15, "us_daily", "=" * 15)
aw = _import_ai_writer("us_daily")
empty = {"top_movers": [{"ticker": "AAPL"}], "news": []}
full = {"top_movers": [{"ticker": "AAPL"}], "news": [{"title": "x"}]}
fake = """
오늘 미국증시 핵심
### 📊 3대 지수
### 🔥 오늘의 주목 종목
"""
_reproduce("미국증시 데일리", aw, empty, full, fake, "US_DAILY_REQUIRED_SECTIONS")

print("\n" + "=" * 15, "us_weekly", "=" * 15)
aw = _import_ai_writer("us_weekly")
empty = {"top_movers": [], "news": []}
full = {"top_movers": [{"ticker": "AAPL"}], "news": [{"title": "x"}]}
fake = """
이번 주 미국증시 핵심
### 📊 주간 3대 지수 성적
### 🔥 한국인 관심 종목 주간 성적
### 💬 이번 주를 돌아보며
### 🔮 다음 주 전망
"""
_reproduce("미국증시 위클리", aw, empty, full, fake, "US_WEEKLY_REQUIRED_SECTIONS")

print("\n" + "=" * 60)
bad = results.count(False)
print(f"총 {len(results)}건 검사 / 실패 {bad}건 (API 호출 0건)")
sys.exit(1 if bad else 0)
