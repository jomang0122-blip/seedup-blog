# -*- coding: utf-8 -*-
"""
SeedUP 주식공부 — 초안 생성 (발행 아님)
AI로 글을 생성해 _drafts/ 폴더에 JSON+미리보기 HTML로 저장한다.
총괄이 미리보기를 검토하고, 차트 요청 자리에 캡처 이미지를 넣은 뒤(insert_chart.py),
승인(approve.py)하면 main.py가 발행 큐에서 꺼내 발행한다.

실행: python jobs/edu_weekly/draft.py [--topic-id N]
"""
import argparse
import json
import re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ai_writer 임포트 시점에 win32 콘솔 UTF-8 래핑이 이미 처리된다 — 이 파일에서
# 별도로 sys.stdout을 다시 래핑하면 이중 래핑으로 "I/O operation on closed file"
# 오류가 난다(2026-08-18 로컬 테스트에서 확인, 이 파일을 import하는 insert_chart.py·
# approve.py도 동일 이유로 별도 래핑하지 않음).
from topic_manager import get_next_topic
from ai_writer import generate_post
from validator import validate_sections, count_text_length, find_key3_bracket_leak
from shared.utils import find_kanji
from shared.validator import apply_structural_fixes

DRAFTS_DIR = Path(__file__).parent / "_drafts"
DRAFTS_DIR.mkdir(exist_ok=True)

_CHART_REQUEST_RE = re.compile(
    r'<!--\s*CHART_REQUEST\s+pattern="([^"]*)"\s+period="([^"]*)"\s+note="([^"]*)"\s*-->'
)


def log(msg: str):
    print(f"[초안] {msg}")


def _slug(title: str) -> str:
    """파일명용 — 부제(— 이후) 제거, 한글/영문/숫자 외 문자는 제거."""
    short = title.split("—")[0].strip()
    short = re.sub(r"[^0-9A-Za-z가-힣]+", "", short)
    return short[:30]


def _draft_paths(topic: dict) -> dict:
    base = DRAFTS_DIR / f"{topic['id']:02d}_{_slug(topic['title'])}"
    return {
        "json":    base.with_suffix(".json"),
        "preview": Path(str(base) + "_preview.html"),
        "charts":  Path(str(base) + "_charts"),
    }


def _find_draft_json(topic_id: int) -> Path:
    matches = list(DRAFTS_DIR.glob(f"{topic_id:02d}_*.json"))
    if not matches:
        raise FileNotFoundError(f"id={topic_id} 초안을 찾을 수 없습니다 — 먼저 draft.py로 생성하세요.")
    if len(matches) > 1:
        raise RuntimeError(f"id={topic_id} 초안이 여러 개 발견됨: {[m.name for m in matches]} — 하나만 남기고 정리하세요.")
    return matches[0]


def _find_chart_requests(content: str) -> list:
    return [
        {"index": i + 1, "pattern": m.group(1), "period": m.group(2), "note": m.group(3)}
        for i, m in enumerate(_CHART_REQUEST_RE.finditer(content))
    ]


def _build_preview_html(topic: dict, post: dict, chart_requests: list, review_issues: list = None) -> str:
    """총괄이 브라우저로 여는 미리보기 — CHART_REQUEST 자리와 AI 자체검토 결과를 눈에 띄게 표시."""
    body = post["content"]

    def _render_chart_box(m):
        pattern, period, note = m.group(1), m.group(2), m.group(3)
        return (
            '<div style="margin:16px 0;padding:16px 18px;background:#fff7e6;'
            'border:2px dashed #f5a623;border-radius:8px;font-family:sans-serif;">'
            '<p style="margin:0 0 6px 0;font-weight:700;color:#b9770e;">📊 차트 필요</p>'
            f'<p style="margin:0;font-size:14px;color:#555;">대상: {pattern}<br>'
            f'기간: {period}<br>표시요청: {note}</p>'
            '<p style="margin:8px 0 0 0;font-size:12px;color:#999;">'
            '[ insert_chart.py로 이 자리에 캡처 이미지를 삽입하세요 ]</p>'
            '</div>'
        )

    body_preview = _CHART_REQUEST_RE.sub(_render_chart_box, body)

    chart_status = (
        f"차트 요청 {len(chart_requests)}건 — 전부 캡처 후 insert_chart.py로 삽입 필요"
        if chart_requests else "차트 요청 없음"
    )

    if review_issues:
        items = "".join(f"<li style='margin-bottom:4px;'>{i}</li>" for i in review_issues)
        review_box = (
            '<div style="margin:0 0 20px 0;padding:16px 18px;background:#fff0f0;'
            'border:2px solid #e74c3c;border-radius:8px;font-family:sans-serif;">'
            '<p style="margin:0 0 8px 0;font-weight:700;color:#c0392b;">🔍 AI 자체검토 결과 — 확인 필요</p>'
            f'<ul style="margin:0;padding-left:20px;font-size:14px;color:#555;">{items}</ul>'
            "</div>"
        )
    elif review_issues is None:
        # None = 자동검토 미실행(크레딧 절약, 2026-08-19) — 총괄이 직접 검토하는 단계임을
        # "문제없음"과 구분해서 표시. 빈 리스트([])는 실제로 검토했고 클린한 경우에만 씀.
        review_box = (
            '<div style="margin:0 0 20px 0;padding:10px 16px;background:#f5f5f5;'
            'border-radius:8px;font-size:13px;color:#888;">⏸️ AI 자체검토 미실행 — 총괄 직접 검토 필요</div>'
        )
    else:
        review_box = (
            '<div style="margin:0 0 20px 0;padding:10px 16px;background:#eafaf1;'
            'border-radius:8px;font-size:13px;color:#27ae60;">✅ AI 자체검토: 문제 없음</div>'
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>[미리보기] {post['title']}</title></head>
<body style="max-width:640px;margin:30px auto;font-family:-apple-system,'Malgun Gothic',sans-serif;">
<div style="padding:12px 16px;background:#eef4ff;border-radius:8px;margin-bottom:20px;font-size:13px;color:#3182f6;">
주제 ID {topic['id']} · 카테고리 {topic['category']} · 레벨 {topic['level']} · {chart_status}<br>
글자수 {post['char_count']}자 · 라벨 {', '.join(post['labels'])}
</div>
{review_box}
{body_preview}
</body></html>"""


def generate_draft(topic_id: int = None) -> dict:
    topic = get_next_topic(topic_id)
    if topic is None:
        log("모든 주제 발행 완료 — 생성할 주제가 없습니다.")
        return None

    log(f"주제: [{topic['level']}] {topic['title']} (id={topic['id']}, 카테고리={topic['category']})")

    post = None
    fail_reason = None
    for attempt in range(3):
        try:
            candidate = generate_post(topic)
        except Exception as e:
            fail_reason = f"글 생성 실패: {e}"
            log(f"[재시도 {attempt + 1}/3] {fail_reason}")
            continue
        missing = validate_sections(candidate["content"])
        if missing:
            fail_reason = f"누락 섹션: {missing}"
            log(f"[재시도 {attempt + 1}/3] {fail_reason}")
            continue
        bracket_leak = find_key3_bracket_leak(candidate["content"])
        if bracket_leak:
            fail_reason = f"대괄호 플레이스홀더 잔존: {bracket_leak}"
            log(f"[재시도 {attempt + 1}/3] {fail_reason}")
            continue
        kanji = find_kanji(candidate["title"] + candidate["content"])
        if kanji:
            fail_reason = f"한자 검출: {sorted(set(kanji))}"
            log(f"[재시도 {attempt + 1}/3] {fail_reason}")
            continue
        post = candidate
        break

    if post is None:
        raise RuntimeError(f"3회 모두 검증 실패(마지막 사유: {fail_reason}) — 초안 생성 중단")

    post["content"], structural_issues = apply_structural_fixes(post["content"], check_disclaimer=False)
    post["char_count"] = len(post["content"])
    if structural_issues:
        for si in structural_issues:
            log(f"  [{si['type']}] {si['description']}")

    chart_requests = _find_chart_requests(post["content"])
    if not chart_requests:
        log("  [경고] CHART_REQUEST 플레이스홀더가 없음 — AI가 누락했을 수 있음, 미리보기 확인 필요")

    # review_post() 자동 호출 폐기(2026-08-19) — 별도 Anthropic API 크레딧을 쓰는 데다
    # 이미지 접근이 없어 총괄이 직접 캡처로 확인한 실제 수치를 "검증 불가"로 오탐하는
    # 문제도 있었다(SK하이닉스 1,168,000원 건). 크레딧은 초안 생성(1회)에만 쓰고,
    # 검토는 총괄과 함께 이 세션에서 직접 진행한다. review_issues=None은 "검토 안 함"
    # 상태 — 빈 리스트([])인 "검토했고 문제없음"과 미리보기에서 다르게 표시된다.
    review_issues = None

    paths = _draft_paths(topic)
    record = {
        "topic_id":       topic["id"],
        "topic_title":    topic["title"],
        "level":          topic["level"],
        "category":       topic["category"],
        "title":          post["title"],
        "labels":         post["labels"],
        "content":        post["content"],
        "char_count":     post["char_count"],
        "chart_requests": chart_requests,
        "review_issues":  review_issues,
        "approved":       False,
    }
    paths["json"].write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["preview"].write_text(_build_preview_html(topic, post, chart_requests, review_issues), encoding="utf-8")
    if chart_requests:
        paths["charts"].mkdir(exist_ok=True)

    log(f"저장 완료: {paths['json'].name}")
    log(f"미리보기: {paths['preview']}")
    if chart_requests:
        log(f"차트 요청 {len(chart_requests)}건 → 이미지를 {paths['charts'].name}/ 에 넣고 insert_chart.py 실행하세요")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 주식공부 초안 생성")
    parser.add_argument("--topic-id", type=int, default=None, help="특정 주제 ID 지정 (기본: 다음 미발행 주제)")
    args = parser.parse_args()
    generate_draft(topic_id=args.topic_id)
