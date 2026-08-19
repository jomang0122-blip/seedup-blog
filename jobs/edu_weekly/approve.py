# -*- coding: utf-8 -*-
"""
SeedUP 주식공부 — 초안 승인 (발행 큐에 등록)
차트 요청이 전부 채워지고 내용에 문제가 없는 초안을 _drafts/_approved/로 옮긴다.
main.py는 이 폴더에서 오래된 순서로 하나씩 꺼내 발행한다.

실행: python jobs/edu_weekly/approve.py --id 1
"""
import argparse
import json
from pathlib import Path

# draft 임포트 시점에 콘솔 UTF-8 래핑이 이미 처리됨 — 이중 래핑 방지(draft.py 주석 참고)
from draft import DRAFTS_DIR, _CHART_REQUEST_RE, _find_draft_json
from shared.utils import find_kanji

APPROVED_DIR = DRAFTS_DIR / "_approved"
APPROVED_DIR.mkdir(exist_ok=True)


def log(msg: str):
    print(f"[승인] {msg}")


def approve(topic_id: int) -> None:
    json_path = _find_draft_json(topic_id)
    record = json.loads(json_path.read_text(encoding="utf-8"))

    remaining_charts = list(_CHART_REQUEST_RE.finditer(record["content"]))
    if remaining_charts:
        raise ValueError(
            f"아직 처리되지 않은 차트 요청이 {len(remaining_charts)}건 남아있습니다 — "
            "insert_chart.py로 전부 삽입한 뒤 승인하세요."
        )

    kanji = find_kanji(record["title"] + record["content"])
    if kanji:
        raise ValueError(f"한자가 검출됐습니다: {sorted(set(kanji))} — 승인할 수 없습니다.")

    record["approved"] = True
    dest = APPROVED_DIR / json_path.name
    dest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.unlink()
    preview = json_path.with_name(json_path.stem + "_preview.html")
    if preview.exists():
        preview.unlink()

    log(f"승인 완료 — 발행 큐에 등록됨: {dest.name}")
    log(f"현재 큐 대기: {len(list(APPROVED_DIR.glob('*.json')))}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="초안 승인 → 발행 큐 등록")
    parser.add_argument("--id", type=int, required=True, help="주제 ID")
    args = parser.parse_args()
    approve(args.id)
