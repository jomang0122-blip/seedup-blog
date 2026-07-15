# -*- coding: utf-8 -*-
"""
SeedUP 국내증시 위클리 자동 발행 파이프라인
실행: python jobs/kr_weekly/main.py [--dry-run] [--force]
"""
import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import pytz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from data_collector import collect_all
from ai_writer import generate_post
from shared.validator import validate_post, apply_corrections, apply_structural_fixes, assert_market_keywords
from shared.blog_publisher import publish_post, check_today_post

KST      = pytz.timezone("Asia/Seoul")
REPO_ROOT = Path(__file__).parent.parent.parent
LOG_DIR   = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def build_title(data: dict) -> str:
    """제목을 Python에서 강제 조립."""
    week_start = data.get("week_start", "")
    week_end   = data.get("week_end", "")
    try:
        s = datetime.strptime(week_start, "%Y-%m-%d")
        e = datetime.strptime(week_end, "%Y-%m-%d")
        if s.month == e.month:
            date_range = f"{s.month}월 {s.day}일~{e.day}일"
        else:
            date_range = f"{s.month}월 {s.day}일~{e.month}월 {e.day}일"
    except Exception:
        date_range = f"{week_start}~{week_end}"

    kospi = data.get("kospi", {})
    pct   = kospi.get("weekly_pct", 0) or 0
    direction = "상승" if pct >= 0 else "하락"
    return f"[{date_range} 국내증시 주간] 코스피 {abs(pct):.1f}% {direction} 주간 시황 리뷰"


def save_log(data: dict, post: dict, result: dict, kst_date: str, validation_issues: list = None):
    log_file = LOG_DIR / f"kr_weekly_{kst_date.replace('-', '')}.json"
    record = {
        "kst_date":     kst_date,
        "week_start":   data.get("week_start"),
        "week_end":     data.get("week_end"),
        "published_at": datetime.now().isoformat(),
        "title":        post.get("title", ""),
        "url":          result.get("url", ""),
        "char_count":   post.get("char_count", 0),
        "kospi_weekly_pct": data.get("kospi", {}).get("weekly_pct"),
        "validation_issues": validation_issues or [],
    }
    log_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"로그 저장: {log_file.name}")


def run(dry_run: bool = False, force: bool = False):
    kst_now  = datetime.now(KST)
    kst_date = kst_now.strftime("%Y-%m-%d")

    log("=" * 50)
    log(f"SeedUP 국내증시 위클리  {'[DRY-RUN]' if dry_run else '[LIVE]'}  KST {kst_now.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 50)

    # 토요일(5)에만 발행 — force 시 생략
    if not force and kst_now.weekday() != 5:
        log(f"  오늘은 {kst_now.strftime('%A')} — 토요일에만 발행합니다. 종료.")
        sys.exit(0)

    log("▶ Step 1: 국내 주간 데이터 수집")
    try:
        data = collect_all()
    except Exception as e:
        log(f"  [오류] 데이터 수집 실패: {e}")
        sys.exit(1)

    if not data.get("week_start"):
        log("  데이터 없음 — 발행 생략")
        sys.exit(0)

    if not data.get("kospi", {}).get("close"):
        log("  [오류] KOSPI 지수 누락 — 품질 게이트: 발행 중단")
        sys.exit(1)

    kospi = data.get("kospi", {})
    log(f"  주간 범위: {data['week_start']} ~ {data['week_end']}")
    log(f"  KOSPI: {kospi.get('close', 'N/A')} (주간 {kospi.get('weekly_pct', 0):+.2f}%)")
    log(f"  급등 {len(data.get('top_gainers', []))}종목  급락 {len(data.get('top_losers', []))}종목  뉴스 {len(data.get('news', []))}건")

    log("▶ Step 2: 제목 조립 (Python 강제)")
    title = build_title(data)
    log(f"  제목: {title}")


    log("▶ Step 3: AI 블로그 콘텐츠 생성 + 검증 (반복서술·근거없는 창작 시 재생성, 최대 3회)")
    post = None
    validation_issues = []
    prev_issues = None
    for attempt in range(3):
        try:
            candidate = generate_post(data, prev_issues=prev_issues)
            candidate["title"] = title
            if not candidate["content"]:
                raise ValueError("콘텐츠가 비어 있습니다.")
            log(f"  글자수: {candidate['char_count']}자")
        except Exception as e:
            log(f"  [오류] 콘텐츠 생성 실패: {e}")
            sys.exit(1)

        try:
            assert_market_keywords(candidate["content"], ["코스피", "KOSPI"], "국내증시(코스피)")
        except ValueError as e:
            log(f"  [경고] {e}")
            if attempt < 2:
                log(f"  [재시도 {attempt + 1}/3] 다른 시장 콘텐츠 의심 — 글 재생성")
                continue
            log("  [오류] 3회 모두 시장 키워드 검증 실패 — 발행 중단")
            sys.exit(1)

        log("▶ Step 3-1: 수치 검증")
        try:
            validation = validate_post(data, candidate)
        except Exception as e:
            log(f"  [경고] 검증 실패 (발행은 계속): {e}")
            post = candidate
            break

        if validation["approved"]:
            log("  검증 통과 — 수치 이상 없음")
            post = candidate
            break

        validation_issues = validation["issues"]
        log(f"  오류 {len(validation['issues'])}개 발견")
        for issue in validation["issues"]:
            log(f"     [{issue['type']}] {issue['description']}")

        if validation.get("needs_regenerate") and attempt < 2:
            log(f"  [재시도 {attempt + 1}/3] 반복서술·근거없는 뉴스창작 감지 — 글 재생성")
            prev_issues = validation["issues"]
            continue

        candidate = apply_corrections(candidate, validation)
        corr_log = candidate.pop("_correction_log", {"applied": [], "skipped": []})
        log(f"  수정 후 제목: {candidate['title']}")
        log(f"  본문 자동교정: 적용 {len(corr_log['applied'])}건 / 건너뜀 {len(corr_log['skipped'])}건")
        post = candidate
        break

    if post is None:
        log("  [오류] 3회 모두 검증 실패 — 발행 중단")
        sys.exit(1)

    log("▶ Step 3-2: 구조 검증 (색상 태그 중첩·면책조항 누락)")
    post["content"], structural_issues = apply_structural_fixes(post["content"])
    post["char_count"] = len(post["content"])
    if structural_issues:
        validation_issues.extend(structural_issues)
        for si in structural_issues:
            log(f"     [{si['type']}] {si['description']}")
    else:
        log("  구조 이상 없음")

    if dry_run:
        log("▶ [DRY-RUN] 발행 생략 — 미리보기")
        print("\n" + "─" * 60)
        print(f"제목: {post['title']}")
        print(f"라벨: {post['labels']}")
        print(f"\n{post['content'][:500]}...(이하 생략)")
        print("─" * 60)
        log("DRY-RUN 완료")
        return

    log("▶ Step 4: 중복 발행 체크")
    if force:
        log("  --force 지정 — 중복 체크 생략")
    else:
        try:
            existing = check_today_post(kst_date, label_filter="국내증시 주간]")
            if existing:
                log(f"  오늘 이미 발행됨 — 중복 발행 생략: {existing['url']}")
                sys.exit(0)
            log("  중복 없음 — 발행 진행")
        except Exception as e:
            log(f"  [경고] 중복 체크 실패 (발행은 계속): {e}")

    log("▶ Step 5: Blogger 발행")
    try:
        result = publish_post(
            title=post["title"],
            content=post["content"],
            labels=post.get("labels", ["국내증시", "코스피", "위클리"]),
            status="LIVE",
        )
        log(f"  발행 완료!")
        log(f"  URL: {result['url']}")
        save_log(data, post, result, kst_date, validation_issues)
    except Exception as e:
        log(f"  [오류] 발행 실패: {e}")
        sys.exit(1)

    log("=" * 50)
    log("전체 파이프라인 완료")
    log("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 국내증시 위클리 자동 발행")
    parser.add_argument("--dry-run", action="store_true", help="발행 없이 미리보기만")
    parser.add_argument("--force",   action="store_true", help="중복 체크 무시하고 강제 재발행")
    args = parser.parse_args()
    run(dry_run=args.dry_run, force=args.force)
