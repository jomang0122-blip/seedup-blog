# -*- coding: utf-8 -*-
"""
SeedUP 국내증시 데일리 자동 발행 파이프라인
실행: python jobs/kr_daily/main.py [--dry-run] [--date YYYYMMDD] [--force]
"""
import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from data_collector import collect_all
from ai_writer import generate_post
from shared.validator import validate_post, apply_corrections
from shared.blog_publisher import publish_post, check_today_post

REPO_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def save_log(data: dict, post: dict, result: dict):
    date_str = data.get("date", datetime.today().strftime("%Y-%m-%d")).replace("-", "")
    log_file = LOG_DIR / f"kr_daily_{date_str}.json"
    record = {
        "date": data.get("date"),
        "published_at": datetime.now().isoformat(),
        "title": post["title"],
        "url": result.get("url", ""),
        "char_count": post["char_count"],
        "kospi_close": data.get("kospi", {}).get("close"),
        "kospi_change_pct": data.get("kospi", {}).get("change_pct"),
    }
    log_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"로그 저장: {log_file.name}")


def is_trading_day(date_str: str) -> bool:
    import FinanceDataReader as fdr
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    try:
        df = fdr.DataReader("KS11", date_fmt, date_fmt)
        return not df.empty
    except Exception:
        return False


def run(dry_run: bool = False, date: str = None, force: bool = False):
    log("=" * 50)
    log(f"SeedUP 국내증시 데일리  {'[DRY-RUN]' if dry_run else '[LIVE]'}")
    log("=" * 50)

    if date is None:
        today = datetime.today().strftime("%Y%m%d")
        if not is_trading_day(today):
            log(f"  오늘({today})은 휴장일입니다 — 발행 생략")
            sys.exit(0)

    log("▶ Step 1: 시장 데이터 수집")
    try:
        data = collect_all(date)
        kospi = data.get("kospi", {})
        log(f"  KOSPI: {kospi.get('close', 'N/A')} ({kospi.get('change_pct', 0):+.2f}%)")
        log(f"  급등 TOP1: {data['top_gainers'][0]['name'] if data['top_gainers'] else '없음'}")
        log(f"  특징주 뉴스: {len(data.get('crawled_news_features', []))}건")
    except Exception as e:
        log(f"  [오류] 데이터 수집 실패: {e}")
        sys.exit(1)

    log("▶ Step 2: AI 블로그 포스팅 생성")
    try:
        post = generate_post(data)
        if not post["title"] or not post["content"]:
            raise ValueError("제목 또는 본문이 비어 있습니다.")
        log(f"  제목: {post['title']}")
        log(f"  글자수: {post['char_count']}자")
    except Exception as e:
        log(f"  [오류] 글 생성 실패: {e}")
        sys.exit(1)

    log("▶ Step 3: 수치 검증 에이전트")
    try:
        validation = validate_post(data, post)
        if validation["approved"]:
            log("  검증 통과 — 수치 이상 없음")
        else:
            log(f"  오류 {len(validation['issues'])}개 발견 — 자동 수정 적용")
            for issue in validation["issues"]:
                log(f"     [{issue['type']}] {issue['description']}")
            post = apply_corrections(post, validation)
            log(f"  수정 후 제목: {post['title']}")
    except Exception as e:
        log(f"  [경고] 검증 실패 (발행은 계속): {e}")

    if dry_run:
        log("▶ [DRY-RUN] 발행 생략 — 미리보기")
        print("\n" + "─" * 60)
        print(f"제목: {post['title']}")
        print(f"라벨: {post['labels']}")
        print(f"\n{post['content'][:500]}...(이하 생략)")
        print("─" * 60)
        log("DRY-RUN 완료")
        return

    log("▶ Step 4: 중복 발행 체크 (현재 비활성화)")
    log("  중복 체크 스킵 — 발행 진행")

    log("▶ Step 5: Blogger 발행")
    try:
        result = publish_post(
            title=post["title"],
            content=post["content"],
            labels=post["labels"],
            status="LIVE",
        )
        log(f"  발행 완료!")
        log(f"  URL: {result['url']}")
        save_log(data, post, result)
    except Exception as e:
        log(f"  [오류] 발행 실패: {e}")
        sys.exit(1)

    log("=" * 50)
    log("전체 파이프라인 완료")
    log("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 국내증시 데일리 자동 발행")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run, date=args.date, force=args.force)
