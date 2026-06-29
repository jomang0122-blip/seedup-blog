# -*- coding: utf-8 -*-
"""
SeedUP 미증시 위클리 자동 발행 파이프라인
실행: python jobs/us_weekly/main.py [--dry-run] [--force]
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
from shared.blog_publisher import publish_post

KST = pytz.timezone("Asia/Seoul")
REPO_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = REPO_ROOT / "logs"
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

    indices = data.get("indices", {})
    ixic = indices.get("^IXIC", {})
    nasdaq_pct = ixic.get("weekly_pct", 0) or 0
    nasdaq_dir = "상승" if nasdaq_pct >= 0 else "하락"

    return f"[{date_range} 미증시 주간] 나스닥 {abs(nasdaq_pct):.1f}% {nasdaq_dir} 주간 리뷰"


def save_log(data: dict, post: dict, result: dict, kst_date: str):
    log_file = LOG_DIR / f"us_weekly_{kst_date.replace('-', '')}.json"
    record = {
        "kst_date": kst_date,
        "week_start": data.get("week_start"),
        "week_end": data.get("week_end"),
        "published_at": datetime.now().isoformat(),
        "title": post.get("title", ""),
        "url": result.get("url", ""),
        "char_count": post.get("char_count", 0),
        "nasdaq_weekly_pct": data["indices"].get("^IXIC", {}).get("weekly_pct"),
    }
    log_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"로그 저장: {log_file.name}")


def run(dry_run: bool = False, force: bool = False):
    kst_now  = datetime.now(KST)
    kst_date = kst_now.strftime("%Y-%m-%d")

    log("=" * 50)
    log(f"SeedUP 미증시 위클리  {'[DRY-RUN]' if dry_run else '[LIVE]'}  KST {kst_now.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 50)

    # 일요일(6)에만 발행 — force 시 생략
    if not force and kst_now.weekday() != 6:
        log(f"  오늘은 {kst_now.strftime('%A')} — 일요일에만 발행합니다. 종료.")
        sys.exit(0)

    log("▶ Step 1: 미국 주간 데이터 수집")
    try:
        data = collect_all()
    except Exception as e:
        log(f"  [오류] 데이터 수집 실패: {e}")
        sys.exit(1)

    if data.get("market_closed"):
        log("  데이터 없음 — 발행 생략")
        sys.exit(0)

    ixic = data["indices"].get("^IXIC", {})
    log(f"  주간 범위: {data['week_start']} ~ {data['week_end']}")
    log(f"  나스닥 주간: {ixic.get('close', 'N/A')} (주간 {ixic.get('weekly_pct', 0):+.2f}%)")
    log(f"  관심 종목: {len(data['fixed_stocks'])}개  급등락: {len(data['top_movers'])}개  뉴스: {len(data['news'])}건")

    log("▶ Step 2: 제목 조립 (Python 강제)")
    title = build_title(data)
    log(f"  제목: {title}")

    log("▶ Step 3: AI 블로그 콘텐츠 생성")
    try:
        post = generate_post(data)
        post["title"] = title
        if not post["content"]:
            raise ValueError("콘텐츠가 비어 있습니다.")
        log(f"  글자수: {post['char_count']}자")
    except Exception as e:
        log(f"  [오류] 콘텐츠 생성 실패: {e}")
        sys.exit(1)

    if dry_run:
        log("▶ [DRY-RUN] 발행 생략 — 미리보기")
        print("\n" + "─" * 60)
        print(f"제목: {post['title']}")
        print(f"라벨: {post['labels']}")
        print(f"\n{post['content'][:500]}...(이하 생략)")
        print("─" * 60)
        log("DRY-RUN 완료")
        return

    log("▶ Step 4: 중복 체크 없음 — 발행 진행")

    log("▶ Step 5: Blogger 발행")
    try:
        result = publish_post(
            title=post["title"],
            content=post["content"],
            labels=post.get("labels", ["미국증시", "위클리", "주간시황"]),
            status="LIVE",
        )
        log(f"  발행 완료!")
        log(f"  URL: {result['url']}")
        save_log(data, post, result, kst_date)
    except Exception as e:
        log(f"  [오류] 발행 실패: {e}")
        sys.exit(1)

    log("=" * 50)
    log("전체 파이프라인 완료")
    log("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 미증시 위클리 자동 발행")
    parser.add_argument("--dry-run", action="store_true", help="발행 없이 미리보기만")
    parser.add_argument("--force",   action="store_true", help="중복 체크 무시하고 강제 재발행")
    args = parser.parse_args()
    run(dry_run=args.dry_run, force=args.force)
