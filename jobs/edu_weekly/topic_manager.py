# -*- coding: utf-8 -*-
"""
주식공부 주제 관리 — edu_topics.json 읽기/쓰기/선택
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

TOPICS_FILE = Path(__file__).parent.parent.parent / "data" / "edu_topics.json"


def load_topics() -> dict:
    """edu_topics.json 전체 로드."""
    with open(TOPICS_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_next_topic(topic_id: int = None) -> dict | None:
    """
    topic_id 지정 시 해당 주제 반환 (published 여부 무관).
    미지정 시: published=false 중 id 오름차순 첫 번째.
    모두 발행 완료면 None 반환.
    """
    data = load_topics()
    topics = data["topics"]

    if topic_id is not None:
        for t in topics:
            if t["id"] == topic_id:
                return t
        raise ValueError(f"topic_id {topic_id} 를 찾을 수 없습니다.")

    for t in sorted(topics, key=lambda x: x["id"]):
        if not t["published"]:
            return t

    return None  # 52개 모두 완료


def peek_next(current_id: int) -> dict | None:
    """current_id 바로 다음 번호(current_id+1) 주제를 반환 (다음 시간 예고용). 없으면 None.

    과거에는 published 플래그로 "다음 미발행 주제"를 찾았으나, 87개 전체를 1번부터
    순서대로 재작성하는 지금 시기에는 id1~61이 예전 기준 published=true로 남아있어
    (Blogger에서는 비공개 처리했지만 데이터는 아직 안 바뀜) 엉뚱하게 훨씬 뒤(id62 등)를
    "다음 시간"으로 잘못 가리키는 문제가 있었다(2026-08-18 발견). 지금 실제 발행 순서가
    id 오름차순 그대로이므로, published 여부와 무관하게 단순히 current_id+1을 반환한다."""
    data = load_topics()
    return next((t for t in data["topics"] if t["id"] == current_id + 1), None)


def mark_published(topic_id: int, post_url: str) -> None:
    """발행 완료 처리 — published=true, 날짜·URL 기록, meta 갱신."""
    data = load_topics()

    for t in data["topics"]:
        if t["id"] == topic_id:
            t["published"]    = True
            t["published_at"] = datetime.now().strftime("%Y-%m-%d")
            t["post_url"]     = post_url
            break

    data["meta"]["published_count"] = sum(1 for t in data["topics"] if t["published"])
    data["meta"]["last_updated"]    = datetime.now().strftime("%Y-%m-%d")

    # 원자적 쓰기 — 임시파일에 먼저 쓴 뒤 os.replace()로 교체.
    # 프로세스가 쓰기 도중 중단돼도 edu_topics.json 원본이 손상되지 않음.
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=TOPICS_FILE.parent, prefix=TOPICS_FILE.stem + "_", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, TOPICS_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    print(f"  [주제] ID {topic_id} 발행 완료 처리 — {post_url}")


def get_status() -> str:
    """현재 진행 상황 요약 문자열 반환."""
    data  = load_topics()
    meta  = data["meta"]
    total = meta["total"]
    done  = meta["published_count"]
    return f"진행: {done}/{total}편 완료 (남은 주제: {total - done}편)"


if __name__ == "__main__":
    print(get_status())
    topic = get_next_topic()
    if topic:
        print(f"다음 주제: [{topic['level']}] {topic['title']}")
    else:
        print("모든 주제 발행 완료!")
