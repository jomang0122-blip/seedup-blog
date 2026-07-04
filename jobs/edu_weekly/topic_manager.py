# -*- coding: utf-8 -*-
"""
주식공부 주제 관리 — edu_topics.json 읽기/쓰기/선택
"""
import json
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

    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
