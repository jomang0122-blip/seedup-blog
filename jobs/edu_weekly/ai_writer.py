# -*- coding: utf-8 -*-
"""
주식공부 글 생성 — 레벨별 Claude 프롬프트 (시드업 클래스 v2)
"""
import io
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic
from banner import generate_banner_card, generate_key3_box

client = Anthropic()

# ── 레벨별 작성 지침 ──────────────────────────────────────────────────────────

_LEVEL_GUIDE = {
    "초급": (
        "어투: '~라고 해요', '~해볼까요?', '쉽게 말하면' 등 친근하고 쉬운 표현.\n"
        "비유를 적극 활용하고, 영어 약어는 반드시 한글 풀이 병기 (예: PER(주가수익비율)).\n"
        "독자: 주식을 처음 접하는 직장인. 전문 용어 최소화."
    ),
    "중급": (
        "어투: '~입니다', '~을 고려해야 합니다.' 정중하고 실용적.\n"
        "계산 방법과 실전 판단 기준 포함. 실제 국내 종목 사례 1~2개 언급 가능.\n"
        "독자: 투자 경험 1~3년, 지표는 알지만 활용에 어려움을 느끼는 투자자."
    ),
    "고급": (
        "어투: '~하며', '~관점에서 분석하면' 전문적이고 간결.\n"
        "다른 지표와의 조합 전략, 반례, 한계점까지 다룸. 수치 근거 필수.\n"
        "독자: 투자 경험 3년+, 재무제표를 직접 보는 투자자."
    ),
}

_DISCLAIMER = (
    '<p style="margin-top:30px;padding:15px;background:#f5f5f5;'
    'border-left:4px solid #999;font-size:12px;color:#666;">'
    '⚠️ 본 포스트는 시장 정보 제공 및 교육 목적으로 작성된 것이며, '
    '어떤 식으로든 특정 종목 또는 금융상품의 매매를 추천하는 것이 아닙니다. '
    '투자 결정은 반드시 개인의 투자 목표, 위험 선호도, 재무 상황을 고려하여 '
    '신중히 진행하시기 바랍니다. SeedUP 투자 블로그는 본 내용으로 인한 '
    '모든 직·간접적 손실에 대해 책임을 지지 않습니다. ⚠️</p>'
)


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────────

def _build_prompt(topic: dict) -> str:
    level        = topic["level"]
    title        = topic["title"]
    category     = topic["category"]
    tags         = topic["tags"]
    guide        = _LEVEL_GUIDE[level]
    labels       = ",".join(["주식투자클래스", "투자기초", level] + tags)
    forced_title = f"[{level}] {title}"
    short_title  = title.split("—")[0].strip()

    return f"""당신은 주식 투자 교육 전문가이자 블로그 작가입니다.
SeedUP INVEST 블로그의 '시드업 클래스' 시리즈 포스팅을 HTML 형식으로 작성하세요.

━━━ 이번 주제 ━━━
제목(변경 금지): {forced_title}
난이도: {level}
카테고리: {category}

━━━ 작성 지침 ━━━
{guide}

공통 규칙:
1. HTML 형식 (Blogger에 바로 붙여넣는 포맷)
2. 분량: 본문 텍스트 1,400~1,700자 (HTML 태그 제외, 면책 문구·박스 제외)
   - 🎯 개념 섹션: 최대 500자 / 💡 예시 섹션: 최대 500자 / ⚠️ 주의+예고 섹션: 최대 400자
3. 단락은 2~3문장 이내 — 모바일 가독성 우선
4. 환각 절대 금지 — 수치는 일반적으로 알려진 범위만 사용
5. 배너 카드·h2 제목은 시스템이 자동 삽입 — 본문에 출력 금지

구조 (반드시 이 순서, 태그·이모지 변경 금지):
a) <p><strong>📌 핵심 요약</strong></p>
   <p>이 글에서 배울 내용 2문장 (SEO 스니펫용, 키워드 포함)</p>
b) <!-- KEY3_BOX -->  ← 이 주석을 핵심 요약 바로 뒤에 반드시 삽입 (변경·삭제 금지)
c) <h3>🎯 {short_title}이란?</h3> — 개념 정의 + 왜 중요한가 (400~500자)
d) <h3>💡 실전 활용 예시</h3> — 구체적 수치·상황 포함 (400~500자)
e) <h3>⚠️ 주의사항 & 다음 시간 예고</h3>
   - 주의사항 2~3가지 서술
   - 마지막 줄 반드시 포함: <p>📅 다음 시간 예고: [연관 개념명]에 대해 알아봅니다.</p>

SEO:
- 키워드: {', '.join(tags)}
- 핵심 요약에 키워드 자연스럽게 포함

출력 형식 (헤더 3개 + HTML 본문):
TITLE: {forced_title}
LABELS: {labels}
KEY3:
[핵심 항목 1 — 20자 이내 한 문장]
[핵심 항목 2 — 20자 이내 한 문장]
[핵심 항목 3 — 20자 이내 한 문장]
CONTENT:
[HTML 본문 — a)~e) 순서대로]

⚠️ CONTENT 이후에 체크리스트, 작성 완료 표시, 메모, 주석, 요약 등 어떤 추가 텍스트도 절대 출력하지 말 것."""


# ── 파싱 ─────────────────────────────────────────────────────────────────────

def _parse_response(raw: str, topic: dict) -> dict:
    level    = topic["level"]
    title    = topic["title"]
    category = topic["category"]
    episode  = topic["id"]

    lines          = raw.split("\n")
    parsed_title   = ""
    labels         = []
    key3_items     = []
    content_lines  = []
    mode           = None
    key3_count     = 0

    for line in lines:
        if line.startswith("TITLE:"):
            parsed_title = line.removeprefix("TITLE:").strip()
        elif line.startswith("LABELS:"):
            labels = [l.strip() for l in line.removeprefix("LABELS:").strip().split(",") if l.strip()]
        elif line.startswith("KEY3:"):
            mode = "key3"
            key3_count = 0
        elif line.startswith("CONTENT:"):
            mode = "content"
        elif mode == "key3" and key3_count < 3:
            item = line.strip()
            if item:
                key3_items.append(item)
                key3_count += 1
        elif mode == "content":
            # AI가 CONTENT 뒤에 체크리스트/메타 주석을 출력하면 거기서 중단
            if line.strip().startswith("---") or "작성 완료 체크리스트" in line or line.strip().startswith("### 작성"):
                break
            content_lines.append(line)

    # fallback: CONTENT: 마커 누락 시 LABELS: 이후 전체를 본문으로
    if not content_lines and mode != "content":
        start = next((i + 1 for i, l in enumerate(lines) if l.startswith("LABELS:")), 0)
        content_lines = lines[start:]
        print("  [파싱 경고] CONTENT: 마커 누락 — 폴백 처리")

    forced_title = f"[{level}] {title}"
    body         = "\n".join(content_lines).strip()

    # 핵심 박스 삽입
    banner_html = generate_banner_card(level, category, title, episode)
    key3_html   = generate_key3_box(level, key3_items) if key3_items else ""

    if "<!-- KEY3_BOX -->" in body:
        body = body.replace("<!-- KEY3_BOX -->", key3_html)
    elif key3_html:
        # 폴백: 핵심 요약 두 번째 </p> 뒤에 삽입
        body = _insert_after_summary(body, key3_html)

    # 전체 조립: 배너 + h2 제목 + 본문 + 면책조항
    content = (
        banner_html + "\n"
        + f"<h2>{forced_title}</h2>\n"
        + body + "\n"
        + _DISCLAIMER
    )

    return {
        "title":      forced_title,
        "labels":     labels,
        "content":    content,
        "char_count": len(content),
    }


def _insert_after_summary(body: str, key3_html: str) -> str:
    """핵심 요약 단락(두 번째 </p>) 뒤에 key3 박스를 삽입한다."""
    import re
    pattern = r'(📌 핵심 요약.+?</p>\s*<p>.+?</p>)'
    m = re.search(pattern, body, flags=re.DOTALL)
    if m:
        end = m.end()
        return body[:end] + "\n" + key3_html + body[end:]
    return key3_html + "\n" + body


# ── 공개 API ─────────────────────────────────────────────────────────────────

def generate_post(topic: dict, model: str = "claude-haiku-4-5-20251001") -> dict:
    """주제 dict → Claude → {title, labels, content, char_count}"""
    prompt  = _build_prompt(topic)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw    = message.content[0].text
    result = _parse_response(raw, topic)
    print(f"  [작성] 제목: {result['title']}")
    print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")
    return result


# ── 단독 테스트 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample = {
        "id": 1,
        "title": "주식이란 무엇인가 — 소유권과 배당의 개념",
        "level": "초급",
        "category": "투자기초",
        "tags": ["주식기초", "주식이란", "배당"],
    }
    post = generate_post(sample)
    print(f"\n── 생성된 포스트 ──")
    print(f"제목: {post['title']}")
    print(f"라벨: {post['labels']}")
    print(f"글자수: {post['char_count']}")
    print(f"\n── HTML 본문 (앞 800자) ──")
    print(post["content"][:800])
