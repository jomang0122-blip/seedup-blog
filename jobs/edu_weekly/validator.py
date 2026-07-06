# -*- coding: utf-8 -*-
"""
시드업 클래스 — 생성된 HTML 후처리 검증
"""
import re

# (표시명, 정규식) — 검증은 조립 완료된 content(배너+본문+면책)로 실행되므로,
# 고정 조립부에도 항상 존재하는 문자열(예: 면책의 ⚠️)로 검사하면 본문 누락을
# 못 잡는다. 소제목은 헤딩 태그 기준으로 검사한다 (지시는 h2이나, AI가
# h3으로 출력해도 발행이 막히지 않도록 h2/h3 모두 허용).
REQUIRED_SECTIONS = [
    ("📌 핵심 요약",      r"📌\s*핵심 요약"),
    ("오늘의 핵심 3가지", r"오늘의 핵심 3가지"),
    ("🎯 개념 소제목",    r"<h[23]>[^<]*🎯"),
    ("💡 실전 예시",      r"<h[23]>[^<]*💡"),
    ("⚠️ 주의사항",       r"<h[23]>[^<]*⚠"),
]


def validate_sections(html: str) -> list:
    """누락된 섹션 이름 목록 반환. 빈 리스트이면 정상."""
    return [name for name, pattern in REQUIRED_SECTIONS if not re.search(pattern, html)]


def count_text_length(html: str) -> int:
    """HTML 태그 제거 후 순수 텍스트 글자수 반환."""
    text = re.sub(r'<[^>]+>', '', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return len(text)
