# -*- coding: utf-8 -*-
"""
SeedUP 주식공부 주간 자동 발행 파이프라인 (승인 큐 방식, 2026-08-18 개편)

기존에는 이 스크립트가 실행 시점에 AI로 즉석 생성→검증→발행까지 한 번에 처리했으나,
글 퀄리티(차트가 이론과 일치하는지, 내용이 총괄 검토를 거쳤는지)를 담보할 수 없어
아래 방식으로 바꿨다:
  1) draft.py로 미리 초안 생성 (여러 개 미리 만들어둘 수 있음)
  2) 총괄이 미리보기(_preview.html)를 검토
  3) insert_chart.py로 캡처 차트 삽입
  4) approve.py로 승인 → _drafts/_approved/ 큐에 등록
  5) 이 스크립트(main.py)는 그 큐에서 가장 오래된 항목 하나를 그대로 발행만 한다
승인된 초안이 없으면 즉석 생성 없이 이번 회차는 건너뛴다(퀄리티 우선 — 준비 안 된
글을 억지로 내보내지 않는다).

실행: python jobs/edu_weekly/main.py [--dry-run] [--force] [--topic-id N]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pytz

from dotenv import load_dotenv
load_dotenv()

# draft 임포트 시점(ai_writer 경유)에 콘솔 UTF-8 래핑이 이미 처리됨 —
# 이 파일에서 별도로 sys.stdout을 다시 래핑하면 이중 래핑으로 "I/O operation on
# closed file" 오류가 난다(2026-08-18 로컬 테스트에서 확인).
from draft import DRAFTS_DIR
from topic_manager import mark_published, get_status
from shared.blog_publisher import publish_post, get_recent_posts_by_label
from tools.archive_class_posts import sanitize, POSTS_DIR, build_curriculum

KST           = pytz.timezone("Asia/Seoul")
REPO_ROOT     = Path(__file__).parent.parent.parent
LOG_DIR       = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
APPROVED_DIR  = DRAFTS_DIR / "_approved"
PUBLISHED_DIR = DRAFTS_DIR / "_published"
APPROVED_DIR.mkdir(exist_ok=True)
PUBLISHED_DIR.mkdir(exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def _next_approved(topic_id: int = None) -> Path | None:
    queued = sorted(APPROVED_DIR.glob("*.json"), key=lambda p: int(p.name.split("_", 1)[0]))
    if not queued:
        return None
    if topic_id is not None:
        for p in queued:
            if int(p.name.split("_", 1)[0]) == topic_id:
                return p
        return None
    return queued[0]


def archive_to_class_folder(record: dict, result: dict, kst_date: str):
    """04_시드업클래스/01_발행글/ 에 발행글 사본을 저장하고 커리큘럼.md를 갱신한다.

    기존에는 tools/archive_class_posts.py를 발행 후 총괄이 수동으로 따로 실행해야
    했는데, 그 수동 단계를 잊어버려 7/12 이후 갱신이 끊긴 상태로 방치돼 있었다
    (2026-08-18 발견). main.py 발행 직후 자동으로 실행하도록 편입."""
    posts_dir = Path(POSTS_DIR)
    posts_dir.mkdir(parents=True, exist_ok=True)
    existing_seqs = [int(f.name[:3]) for f in posts_dir.glob("*.html") if f.name[:3].isdigit()]
    next_seq = max(existing_seqs) + 1 if existing_seqs else 1
    fname = f"{next_seq:03d}_{kst_date.replace('-', '')}_{sanitize(record['title'])}.html"
    header = (
        f"<!-- post-id:{result['id']} | published:{kst_date} | url:{result['url']} -->\n"
        f"<!-- title: {record['title']} -->\n"
    )
    (posts_dir / fname).write_text(header + record["content"], encoding="utf-8")
    log(f"  로컬 아카이브: 04_시드업클래스/01_발행글/{fname}")
    build_curriculum()
    log("  커리큘럼.md 갱신 완료")


def save_log(record: dict, result: dict, kst_date: str):
    log_file = LOG_DIR / f"edu_weekly_{kst_date.replace('-', '')}_{record['topic_id']:02d}.json"
    entry = {
        "kst_date":     kst_date,
        "published_at": datetime.now().isoformat(),
        "topic_id":     record["topic_id"],
        "topic_title":  record["topic_title"],
        "level":        record["level"],
        "category":     record["category"],
        "title":        record.get("title", ""),
        "labels":       record.get("labels", []),
        "url":          result.get("url", ""),
        "char_count":   record.get("char_count", 0),
    }
    log_file.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"로그 저장: {log_file.name}")


def run(dry_run: bool = False, force: bool = False, topic_id: int = None):
    kst_now  = datetime.now(KST)
    kst_date = kst_now.strftime("%Y-%m-%d")
    weekday  = kst_now.weekday()  # Mon=0 ... Sat=5, Sun=6

    log("=" * 55)
    log(f"SeedUP 주식공부  {'[DRY-RUN]' if dry_run else '[LIVE]'}  KST {kst_now.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 55)

    if not force and weekday not in (5, 6):
        log(f"  오늘은 {kst_now.strftime('%A')} — 토요일·일요일에만 발행합니다. 종료.")
        sys.exit(0)

    log("▶ Step 1: 승인 큐에서 발행 대상 선택")
    queue_path = _next_approved(topic_id)
    if queue_path is None:
        if topic_id is not None:
            log(f"  id={topic_id} 승인된 초안이 큐에 없습니다. 종료.")
        else:
            log("  승인된 초안이 없습니다 — 이번 회차는 건너뜁니다.")
            log("  (draft.py로 초안 생성 → insert_chart.py → approve.py 로 큐에 등록해주세요)")
        sys.exit(0)
    record = json.loads(queue_path.read_text(encoding="utf-8"))
    log(f"  선택된 주제: [{record['level']}] {record['topic_title']} (id={record['topic_id']})")
    log(f"  큐 대기: {len(list(APPROVED_DIR.glob('*.json')))}건")

    log("▶ Step 2: 중복 발행 가드 (Blogger 실제 발행 여부 확인)")
    try:
        live = get_recent_posts_by_label("주식투자클래스", max_results=100)
        dup = next((p for p in live if p["title"] == record["title"]), None)
        if dup:
            log(f"  이미 발행됨: {dup['url']}")
            mark_published(record["topic_id"], dup["url"])
            queue_path.rename(PUBLISHED_DIR / queue_path.name)
            log("  발행 기록 복구 완료 — 큐에서 제거, 이번 실행은 발행 생략")
            sys.exit(0)
        log("  중복 없음 — 발행 진행")
    except Exception as e:
        log(f"  [경고] 중복 가드 실패 (발행은 계속): {e}")

    if dry_run:
        log("▶ [DRY-RUN] 발행 생략 — 미리보기")
        print("\n" + "─" * 60)
        print(f"제목: {record['title']}")
        print(f"라벨: {record['labels']}")
        print(f"\n{record['content'][:600]}...(이하 생략)")
        print("─" * 60)
        log("DRY-RUN 완료")
        return

    log("▶ Step 3: Blogger 발행")
    try:
        result = publish_post(
            title=record["title"],
            content=record["content"],
            labels=record.get("labels", ["주식투자클래스", record["category"]]),
            status="LIVE",
        )
        log(f"  발행 완료!")
        log(f"  URL: {result['url']}")
    except Exception as e:
        log(f"  [오류] 발행 실패: {e}")
        sys.exit(1)

    log("▶ Step 4: 발행 완료 처리 (edu_topics.json 업데이트)")
    try:
        mark_published(record["topic_id"], result["url"])
        log(f"  현황: {get_status()}")
    except Exception as e:
        log(f"  [경고] 상태 업데이트 실패: {e}")

    log("▶ Step 5: 로컬 아카이브 (04_시드업클래스/01_발행글)")
    try:
        archive_to_class_folder(record, result, kst_date)
    except Exception as e:
        log(f"  [경고] 로컬 아카이브 실패 (발행 자체는 완료됨): {e}")

    log("▶ Step 6: 로그 저장 + 큐 아카이브")
    save_log(record, result, kst_date)
    queue_path.rename(PUBLISHED_DIR / queue_path.name)
    log(f"  큐 항목 아카이브: {PUBLISHED_DIR.name}/{queue_path.name}")

    log("=" * 55)
    log("전체 파이프라인 완료")
    log("=" * 55)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 주식공부 주간 자동 발행 (승인 큐)")
    parser.add_argument("--dry-run",  action="store_true", help="발행 없이 미리보기만")
    parser.add_argument("--force",    action="store_true", help="요일 체크 무시하고 강제 발행")
    parser.add_argument("--topic-id", type=int, default=None, help="큐 안의 특정 주제 ID 지정 (기본: 가장 오래된 승인 항목)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, force=args.force, topic_id=args.topic_id)
