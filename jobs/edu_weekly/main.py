# -*- coding: utf-8 -*-
"""
SeedUP 주식공부 주간 자동 발행 파이프라인
실행: python jobs/edu_weekly/main.py [--dry-run] [--force]
"""
import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import pytz

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from topic_manager import get_next_topic, mark_published, get_status
from ai_writer import generate_post
from validator import validate_sections, count_text_length
from shared.blog_publisher import publish_post

KST       = pytz.timezone("Asia/Seoul")
REPO_ROOT = Path(__file__).parent.parent.parent
LOG_DIR   = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def save_log(topic: dict, post: dict, result: dict, kst_date: str):
    log_file = LOG_DIR / f"edu_weekly_{kst_date.replace('-', '')}_{topic['id']:02d}.json"
    record = {
        "kst_date":     kst_date,
        "published_at": datetime.now().isoformat(),
        "topic_id":     topic["id"],
        "topic_title":  topic["title"],
        "level":        topic["level"],
        "category":     topic["category"],
        "title":        post.get("title", ""),
        "labels":       post.get("labels", []),
        "url":          result.get("url", ""),
        "char_count":   post.get("char_count", 0),
    }
    log_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"로그 저장: {log_file.name}")


def run(dry_run: bool = False, force: bool = False, topic_id: int = None):
    kst_now  = datetime.now(KST)
    kst_date = kst_now.strftime("%Y-%m-%d")
    weekday  = kst_now.weekday()  # Mon=0 ... Sat=5, Sun=6

    log("=" * 55)
    log(f"SeedUP 주식공부  {'[DRY-RUN]' if dry_run else '[LIVE]'}  KST {kst_now.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 55)

    # 토요일(5) 또는 일요일(6)에만 발행 — force 시 생략
    if not force and weekday not in (5, 6):
        log(f"  오늘은 {kst_now.strftime('%A')} — 토요일·일요일에만 발행합니다. 종료.")
        sys.exit(0)

    log("▶ Step 1: 주제 선택")
    topic = get_next_topic(topic_id)
    if topic is None:
        log("  모든 주제(52편) 발행 완료! 새 주제 추가가 필요합니다.")
        sys.exit(0)
    log(f"  선택된 주제: [{topic['level']}] {topic['title']}")
    log(f"  카테고리: {topic['category']}  태그: {topic['tags']}")
    log(f"  현황: {get_status()}")


    log("▶ Step 3: AI 글 생성 (Claude Haiku)")
    try:
        post = generate_post(topic)
        if not post["content"]:
            raise ValueError("콘텐츠가 비어 있습니다.")
        log(f"  글자수: {post['char_count']}자")
        log(f"  라벨: {post['labels']}")
    except Exception as e:
        log(f"  [오류] 글 생성 실패: {e}")
        sys.exit(1)

    log("▶ Step 3-1: 섹션·분량 검증")
    missing = validate_sections(post["content"])
    if missing:
        log(f"  [경고] 누락 섹션: {missing}")
    else:
        log("  섹션 검증 통과")
    text_len = count_text_length(post["content"])
    log(f"  텍스트 길이: {text_len}자 (목표 1400~1700자)")

    if dry_run:
        log("▶ [DRY-RUN] 발행 생략 — 미리보기")
        print("\n" + "─" * 60)
        print(f"제목: {post['title']}")
        print(f"라벨: {post['labels']}")
        print(f"\n{post['content'][:600]}...(이하 생략)")
        print("─" * 60)
        log("DRY-RUN 완료")
        return

    log("▶ Step 4: Blogger 발행")
    try:
        result = publish_post(
            title=post["title"],
            content=post["content"],
            labels=post.get("labels", ["주식투자클래스", "투자기초"]),
            status="LIVE",
        )
        log(f"  발행 완료!")
        log(f"  URL: {result['url']}")
    except Exception as e:
        log(f"  [오류] 발행 실패: {e}")
        sys.exit(1)

    log("▶ Step 5: 발행 완료 처리 (edu_topics.json 업데이트)")
    try:
        mark_published(topic["id"], result["url"])
        log(f"  현황: {get_status()}")
    except Exception as e:
        log(f"  [경고] 상태 업데이트 실패: {e}")

    log("▶ Step 6: 로그 저장")
    save_log(topic, post, result, kst_date)

    log("=" * 55)
    log("전체 파이프라인 완료")
    log("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 주식공부 주간 자동 발행")
    parser.add_argument("--dry-run",  action="store_true", help="발행 없이 미리보기만")
    parser.add_argument("--force",    action="store_true", help="요일·중복 체크 무시하고 강제 발행")
    parser.add_argument("--topic-id", type=int, default=None, help="특정 주제 ID 지정 (기본: 다음 미발행 주제)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, force=args.force, topic_id=args.topic_id)
