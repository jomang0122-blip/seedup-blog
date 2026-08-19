# -*- coding: utf-8 -*-
"""
SeedUP 주식공부 — 초안의 차트 요청 자리에 총괄이 캡처한 이미지를 삽입
_drafts/에 저장된 초안 JSON을 찾아 N번째 CHART_REQUEST 플레이스홀더를
base64 <img> 태그로 교체하고, 미리보기 HTML도 다시 만든다.

실행: python jobs/edu_weekly/insert_chart.py --id 1 --chart 1 --image "경로/파일.png"
"""
import argparse
import base64
import json
import mimetypes
import re
from pathlib import Path

# draft 임포트 시점에 콘솔 UTF-8 래핑이 이미 처리됨 — 이중 래핑 방지(draft.py 주석 참고)
from draft import _CHART_REQUEST_RE, _build_preview_html, _find_chart_requests, _find_draft_json


def log(msg: str):
    print(f"[차트삽입] {msg}")


def insert_chart(topic_id: int, chart_index: int, image_path: str) -> None:
    json_path = _find_draft_json(topic_id)
    record = json.loads(json_path.read_text(encoding="utf-8"))

    img_path = Path(image_path)
    if not img_path.exists():
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {img_path}")

    mime, _ = mimetypes.guess_type(str(img_path))
    if not mime or not mime.startswith("image/"):
        raise ValueError(f"이미지 파일이 아닌 것으로 보입니다(mime={mime}): {img_path}")

    encoded = base64.b64encode(img_path.read_bytes()).decode("ascii")
    data_uri = f"data:{mime};base64,{encoded}"

    content = record["content"]
    matches = list(_CHART_REQUEST_RE.finditer(content))
    if not matches:
        raise ValueError("본문에 CHART_REQUEST 플레이스홀더가 없습니다 — 이미 전부 삽입됐거나 초안 생성 시 누락된 것입니다.")
    if chart_index < 1 or chart_index > len(matches):
        raise ValueError(f"chart_index={chart_index} 범위 초과 (플레이스홀더 {len(matches)}개 존재)")

    target = matches[chart_index - 1]
    pattern_desc = target.group(1)
    # HTS/MTS 캡처는 원본이 가로로 넓고 글씨가 작아 모바일 우선 폭(640px)에서는
    # 축소될 수밖에 없다 — 원본 크기로 볼 수 있게 이미지를 새 탭 링크로 감싼다
    # (2026-08-18 총괄 피드백: 차트가 너무 작게 보임).
    img_tag = (
        '<p style="text-align:center;margin:16px 0;">'
        f'<a href="{data_uri}" target="_blank" rel="noopener">'
        f'<img src="{data_uri}" alt="{pattern_desc} (교육 목적 예시, 투자 권유 아님)" '
        'style="max-width:100%;height:auto;border:1px solid #e5e8eb;border-radius:8px;" />'
        "</a>"
        '<br><span style="font-size:12px;color:#999;">📌 이미지를 누르면 크게 볼 수 있어요</span>'
        "</p>"
    )
    content = content[:target.start()] + img_tag + content[target.end():]
    record["content"] = content
    record["char_count"] = len(re.sub(r"<[^>]+>", "", content))

    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # 미리보기 재생성
    remaining = _find_chart_requests(content)
    topic_stub = {"id": record["topic_id"], "category": record["category"], "level": record["level"]}
    post_stub = {"title": record["title"], "content": content, "char_count": record["char_count"], "labels": record["labels"]}
    preview_path = json_path.with_name(json_path.stem + "_preview.html")
    preview_path.write_text(
        _build_preview_html(topic_stub, post_stub, remaining, record.get("review_issues")),
        encoding="utf-8",
    )

    log(f"삽입 완료: {json_path.name} (요청 #{chart_index}: {pattern_desc})")
    log(f"남은 차트 요청: {len(remaining)}건")
    log(f"미리보기 갱신: {preview_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="초안의 차트 요청 자리에 캡처 이미지 삽입")
    parser.add_argument("--id", type=int, required=True, help="주제 ID")
    parser.add_argument("--chart", type=int, default=1, help="몇 번째 차트 요청인지 (기본 1)")
    parser.add_argument("--image", type=str, required=True, help="캡처 이미지 파일 경로")
    args = parser.parse_args()
    insert_chart(args.id, args.chart, args.image)
