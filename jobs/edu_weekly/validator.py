# -*- coding: utf-8 -*-
"""
시드업 클래스 — 생성된 HTML 후처리 검증
"""
import re

REQUIRED_ANCHORS = [
    "📌 핵심 요약",
    "오늘의 핵심 3가지",
    "🎯",
    "💡",
    "⚠️",
]


def validate_sections(html: str) -> list:
    """누락된 섹션 앵커 목록 반환. 빈 리스트이면 정상."""
    return [anchor for anchor in REQUIRED_ANCHORS if anchor not in html]


def count_text_length(html: str) -> int:
    """HTML 태그 제거 후 순수 텍스트 글자수 반환."""
    text = re.sub(r'<[^>]+>', '', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return len(text)


def validate_and_fix_title(html: str, level: str, title: str) -> str:
    """h2 제목 형식 검증 — [레벨] 대괄호 없으면 강제 교정."""
    correct_h2 = f'<h2>[{level}] {title}</h2>'
    if not re.search(r'<h2>\[.+?\]', html):
        html = re.sub(r'<h2>.*?</h2>', '', html, count=1)
        html = correct_h2 + '\n' + html
    return html
