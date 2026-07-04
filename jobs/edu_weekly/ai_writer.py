# -*- coding: utf-8 -*-
"""
주식공부 글 생성 — 레벨별 Claude 프롬프트
"""
import io
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic

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

_DISCLAIMER = """<p style="margin-top:30px; padding:15px; background:#f5f5f5; border-left:4px solid #999; font-size:12px; color:#666;">⚠️ 본 포스트는 시장 정보 제공 및 교육 목적으로 작성된 것이며, 어떤 식으로든 특정 종목 또는 금융상품의 매매를 추천하는 것이 아닙니다. 투자 결정은 반드시 개인의 투자 목표, 위험 선호도, 재무 상황을 고려하여 신중히 진행하시기 바랍니다. SeedUP 투자 블로그는 본 내용으로 인한 모든 직·간접적 손실에 대해 책임을 지지 않습니다. ⚠️</p>"""


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────────

def _build_prompt(topic: dict) -> str:
    level    = topic["level"]
    title    = topic["title"]
    category = topic["category"]
    tags     = topic["tags"]
    guide    = _LEVEL_GUIDE[level]
    labels   = ",".join(["주식투자클래스", "투자기초", level] + tags)

    short_title = title.split("—")[0].strip()

    return f"""당신은 주식 투자 교육 전문가이자 블로그 작가입니다.
SeedUP INVEST 블로그의 '주식공부' 시리즈 포스팅을 HTML 형식으로 작성하세요.
블로그 설명: "초보부터 고급까지, 주식 투자에 필요한 개념을 매주 쉽게 설명합니다."

━━━ 이번 주제 ━━━
주제명: {title}
난이도: {level}
카테고리: {category}

━━━ 작성 지침 ━━━
{guide}

공통 규칙:
1. HTML 형식 (Blogger에 바로 붙여넣는 포맷)
2. 분량: HTML 태그 포함 2000~2500자 (면책 문구 제외)
3. 단락은 3~4문장 이내로 짧게 — 모바일 가독성 우선
4. 환각 절대 금지 — 수치는 일반적으로 알려진 범위만 사용
5. null/없는 데이터 언급 금지

구조 (반드시 이 순서):
a) <h2> 제목: [{level}] {title}
b) <p><strong>📌 핵심 요약</strong></p> — 이 글에서 배울 내용 2문장 (SEO 스니펫용)
c) <h3>🎯 {short_title}이란?</h3> — 개념 정의 + 왜 중요한가
d) <h3>📐 핵심 원리</h3> — 초급: 원리 2~3가지 / 중급: 계산식+판단기준 / 고급: 정량 분석
e) <h3>💡 실전 활용 예시</h3> — 초급: 가상 예시 / 중급: 국내 종목 사례 / 고급: 전략 조합
f) <h3>⚠️ 주의사항</h3> — 잘못 사용할 때 생기는 오류·함정
g) <h3>🔗 다음 시간 예고</h3> — "다음 주에는 [연관 개념]을 알아봅니다" 1문장
h) 면책 문구: h3 제목 없이 아래 문구를 <p> 태그로만 출력 (한 글자도 바꾸지 말 것):
   ⚠️ 본 포스트는 시장 정보 제공 및 교육 목적으로 작성된 것이며, 어떤 식으로든 특정 종목 또는 금융상품의 매매를 추천하는 것이 아닙니다. 투자 결정은 반드시 개인의 투자 목표, 위험 선호도, 재무 상황을 고려하여 신중히 진행하시기 바랍니다. SeedUP 투자 블로그는 본 내용으로 인한 모든 직·간접적 손실에 대해 책임을 지지 않습니다. ⚠️

SEO:
- 제목에 '주식투자클래스', '{level}', 핵심 키워드 자연스럽게 포함
- 키워드: {', '.join(tags)}

출력 형식 — 아래 3줄 헤더 뒤에 HTML 본문만 작성:
TITLE: [{level}] {title}
LABELS: {labels}
CONTENT:
[HTML 본문]"""


# ── 파싱 ─────────────────────────────────────────────────────────────────────

def _parse_response(raw: str) -> dict:
    title, labels, content_lines = "", [], []
    in_content = False

    for line in raw.split("\n"):
        if line.startswith("TITLE:"):
            title = line.removeprefix("TITLE:").strip()
        elif line.startswith("LABELS:"):
            labels = [l.strip() for l in line.removeprefix("LABELS:").strip().split(",") if l.strip()]
        elif line.startswith("CONTENT:"):
            in_content = True
        elif in_content:
            content_lines.append(line)

    content = "\n".join(content_lines).strip()
    return {"title": title, "labels": labels, "content": content,
            "char_count": len(content)}


# ── 공개 API ─────────────────────────────────────────────────────────────────

def generate_post(topic: dict,
                  model: str = "claude-haiku-4-5-20251001") -> dict:
    """주제 dict → Claude → {title, labels, content, char_count}"""
    prompt  = _build_prompt(topic)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw    = message.content[0].text
    result = _parse_response(raw)

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
    print(f"\n── HTML 본문 (앞 500자) ──")
    print(post["content"][:500])
