# -*- coding: utf-8 -*-
"""
주식공부 글 생성 — 레벨별 Claude 프롬프트 (시드업 클래스 v2)
"""
import io
import re
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic
from banner import generate_banner_card, generate_key3_box
from news_search import search_topic_news
from shared.chart_generator import chart_image_html

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

_CLASS_LINK = (
    '<div style="margin:28px 0 0 0;padding:18px 22px;background:#f0f4ff;'
    'border-radius:10px;border:1px solid #c7d7f5;font-family:-apple-system,\'Malgun Gothic\',sans-serif;">'
    '<p style="margin:0 0 8px 0;font-size:13px;font-weight:700;color:#3182f6;">📚 시드업 클래스 전체 보기</p>'
    '<p style="margin:0;font-size:13px;color:#555;">주식 투자 기초부터 고급 전략까지, 시드업 클래스의 모든 강의를 확인하세요.</p>'
    '<a href="https://www.seedup-invest.com/search/label/%EC%A3%BC%EC%8B%9D%ED%88%AC%EC%9E%90%ED%81%B4%EB%9E%98%EC%8A%A4" '
    'style="display:inline-block;margin-top:12px;padding:8px 18px;background:#3182f6;color:#fff;'
    'border-radius:6px;font-size:13px;font-weight:600;text-decoration:none;">→ 전체 강의 목록 보기</a>'
    '</div>'
)

_DISCLAIMER = (
    '<p style="margin-top:20px;padding:15px;background:#f5f5f5;'
    'border-left:4px solid #999;font-size:12px;color:#666;">'
    '⚠️ 본 포스트는 시장 정보 제공 및 교육 목적으로 작성된 것이며, '
    '어떤 식으로든 특정 종목 또는 금융상품의 매매를 추천하는 것이 아닙니다. '
    '투자 결정은 반드시 개인의 투자 목표, 위험 선호도, 재무 상황을 고려하여 '
    '신중히 진행하시기 바랍니다. SeedUP 투자 블로그는 본 내용으로 인한 '
    '모든 직·간접적 손실에 대해 책임을 지지 않습니다. ⚠️</p>'
)


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────────

def _build_labels(topic: dict) -> list:
    """라벨을 Python에서 고정 생성 — AI의 LABELS: 출력은 신뢰하지 않고 항상 이 값으로 덮어씀."""
    return ["주식투자클래스", "투자기초", topic["level"]] + topic.get("tags", [])


def _build_prompt(topic: dict, news_headlines: list = None) -> str:
    level        = topic["level"]
    title        = topic["title"]
    category     = topic["category"]
    tags         = topic["tags"]
    key_facts    = topic.get("key_facts", [])
    guide        = _LEVEL_GUIDE[level]
    labels       = ",".join(_build_labels(topic))
    forced_title = f"[{level}] {title}"
    short_title  = title.split("—")[0].strip()
    key_facts_block  = "\n".join(f"- {f}" for f in key_facts) if key_facts else ""
    news_block_text  = ""
    if news_headlines:
        lines = "\n".join(f"- {h}" for h in news_headlines)
        news_block_text = (
            f"\n━━━ 최신 관련 뉴스 (실제 사례로 활용 가능) ━━━\n"
            f"아래는 이 주제와 관련된 최근 뉴스입니다. 글에서 자연스럽게 실제 사례로 활용하세요.\n"
            f"뉴스가 직접 관련 없으면 무시하고 key_facts 기반으로만 작성하세요.\n"
            f"{lines}\n"
        )

    chart_note = ""
    if topic.get("chart_index"):
        chart_note = (
            "\n━━━ 참고 차트 안내 ━━━\n"
            "이 글 '실전 활용 예시' 섹션 끝에는 시스템이 최근 실제 지수 차트 이미지를 자동으로 첨부합니다.\n"
            "너는 그 차트의 구체적인 지점·날짜·수치를 알 수 없으므로 절대 단정해서 설명하지 마라.\n"
            "대신 '실전 활용 예시' 섹션 마지막 문장에 '아래 실제 차트에 오늘 배운 개념을 직접 대입해보세요' 같은,\n"
            "차트 내용을 추측하지 않는 자연스러운 안내 문장만 한 줄 추가하라.\n"
        )

    return f"""당신은 주식 투자 교육 전문가이자 블로그 작가입니다.
SeedUP INVEST 블로그의 '시드업 클래스' 시리즈 포스팅을 HTML 형식으로 작성하세요.

━━━ 이번 주제 ━━━
제목(변경 금지): {forced_title}
난이도: {level}
카테고리: {category}

━━━ 반드시 정확하게 포함할 핵심 사실 (변경·생략 금지) ━━━
아래 사실들은 검증된 내용입니다. 글에서 반드시 자연스럽게 포함하고, 이와 다른 수치나 설명을 임의로 만들지 마십시오.
{key_facts_block}
{news_block_text}
{chart_note}
━━━ 작성 지침 ━━━
{guide}

공통 규칙:
1. HTML 형식 (Blogger에 바로 붙여넣는 포맷)
2. 분량: 본문 텍스트 1,400~1,700자 (HTML 태그 제외, 면책 문구·박스 제외)
   - 🎯 개념 섹션: 최대 500자 / 💡 예시 섹션: 최대 500자 / ⚠️ 주의+예고 섹션: 최대 400자
3. 단락은 2~3문장 이내 — 모바일 가독성 우선
4. 환각 절대 금지 — 수치는 일반적으로 알려진 범위만 사용
4-1. 구체적 숫자·기준을 제시할 때 "~면 충분하다", "~하면 된다" 같은 완결형 단정 대신
     "~부터는 효과가 줄어든다", "~을 넘기면 한계가 있다"처럼 방향(상한/하한)이 분명한
     경향성 표현을 사용할 것. 특히 "N개면 충분하다"처럼 하한선인지 상한선인지 헷갈리는
     표현은 금지 — 그 숫자를 넘기면 어떻게 되는지(효과 둔화·한계 등)를 명시해 방향을
     분명히 할 것. "오늘의 핵심 N가지"(KEY3) 항목처럼 글자수 제약이 있는 자리도 이
     방향성만은 반드시 지킬 것.
5. 배너 카드(글 제목 포함)는 시스템이 자동 삽입 — 본문 최상단에 글 제목을 반복 출력 금지 (소제목 h2는 아래 구조대로 출력)

구조 (반드시 이 순서, 태그·이모지 변경 금지):
a) <p><strong>📌 핵심 요약</strong></p>
   <p>이 글에서 배울 내용 2문장 (SEO 스니펫용) — 첫 문장은 반드시 주제 핵심 키워드({short_title})로 시작할 것 (검색 결과 설명문에 그대로 노출됨)</p>
b) <!-- KEY3_BOX -->  ← 이 주석을 핵심 요약 바로 뒤에 반드시 삽입 (변경·삭제 금지)
c) <h2>🎯 [소제목]</h2> — 개념 정의 + 왜 중요한가 (400~500자)
   소제목: {short_title}을 독자에게 자연스러운 한국어 문장으로 표현.
   '이란?'·'란?' 고정 패턴 절대 금지 — 주제에 맞게 자유롭게 작성.
   예) "어떤 차이가 있을까?", "왜 알아야 할까?", "어떻게 읽을까?", "어떻게 활용할까?"
d) <h2>💡 실전 활용 예시</h2> — 구체적 수치·상황 포함 (400~500자)
e) <h2>⚠️ 주의사항</h2>
   - 주의사항 2~3가지 서술 (다음 시간 예고 출력 금지 — 시스템이 자동 삽입)

비유 규칙 (개념 전달력):
- 비유는 정확히 1개만 사용. 개념 섹션 첫 두 문장 안에 배치하고,
  실전 예시 섹션에서 같은 비유를 한 번 더 회수(수미상관)할 것.
- 예시의 수치는 '가상의 투자자 A씨' 프레임 또는 위 key_facts 수치만 사용.
  실존 기업 언급 자체는 레벨 가이드·뉴스 블록이 허용하는 범위에서 가능하나,
  실존 기업의 주가·실적 등 구체 수치를 임의로 지어내는 것은 절대 금지.

문체 규칙 (기계적 반복 금지):
- 같은 종결어미 3문장 연속 금지 — 단, 변주는 위 '작성 지침'의 어투 범위 안에서만 (반말 서술체 금지). 한 문단 안에 짧은 문장을 1개 이상 섞을 것.
- 이모지는 지정된 소제목 외 본문에 추가 금지.
- '한편', '또한'으로 시작하는 문단은 2개 이하.

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

⚠️ 위 KEY3/CONTENT 예시의 대괄호 [ ]는 "이 자리에 내용을 채워라"라는 형식 설명 기호일 뿐이다.
실제 출력에는 대괄호 문자 자체를 절대 포함하지 마라 — 순수 문장만 그대로 적어라.
예) 올바른 KEY3 항목: PER = 주가 ÷ EPS
    잘못된 KEY3 항목: [PER = 주가 ÷ EPS]  ← 대괄호를 그대로 남기면 안 됨

⚠️ CONTENT 이후에 체크리스트, 작성 완료 표시, 메모, 주석, 요약 등 어떤 추가 텍스트도 절대 출력하지 말 것."""


# ── 파싱 ─────────────────────────────────────────────────────────────────────

def _clean_key3_item(item: str) -> str:
    r"""KEY3 한 줄에서 AI가 프롬프트 예시의 대괄호 표기를 그대로 따라 출력한 경우를 제거한다.

    과거 버그(2026-07-04~07-06, 발행 12편 중 8편에서 대괄호 노출):
    이전 로직 re.sub(r"^\[(.+)\]$", r"\1", item)은 줄 전체가 정확히 "[...]"
    형태일 때만 동작 — 끝에 마침표가 붙거나("[...]." ) AI가 자체 번호매김을
    앞에 붙이면("1. [...]") 매칭에 실패해 대괄호가 그대로 남았다.
    대괄호는 이 항목(20자 이내 핵심 한 문장)에 정상적으로 등장할 이유가 없으므로,
    위치에 상관없이 무조건 제거하는 방식으로 교체한다.
    """
    item = re.sub(r"^\d+[.)]\s*", "", item)   # AI가 자체적으로 붙인 "1. " 번호 제거
    item = re.sub(r"^[-•]\s*", "", item)       # 불릿 기호 제거
    item = item.replace("[", "").replace("]", "")
    return item.strip()


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
                item = _clean_key3_item(item)
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

    # 본문(배너·면책조항 조립 전)이 비정상적으로 짧으면 여기서 실패 처리 —
    # 조립 후 content는 배너+면책조항 때문에 항상 비어있지 않게 되어 안전장치가 무력화되므로,
    # 조립 전 원본 body 단계에서 검사해야 실제로 의미가 있음.
    if len(body) < 50:
        raise ValueError(f"AI 본문이 비정상적으로 짧음(조립 전 {len(body)}자) — 파싱 실패로 간주")

    # 핵심 박스 삽입
    banner_html = generate_banner_card(level, category, title, episode)
    key3_html   = generate_key3_box(level, key3_items) if key3_items else ""

    if "<!-- KEY3_BOX -->" in body:
        body = body.replace("<!-- KEY3_BOX -->", key3_html)
    elif key3_html:
        # 폴백: 핵심 요약 두 번째 </p> 뒤에 삽입
        body = _insert_after_summary(body, key3_html)

    # 참고 차트 삽입(선정된 4개 주제만) — AI가 차트 내용을 단정하지 않도록
    # "참고용" 캡션으로만 프레이밍한다(오해 방지, 2026-07-05 확정)
    if topic.get("chart_index"):
        short_title = title.split("—")[0].strip()
        chart_html = chart_image_html(
            topic["chart_index"], days=60,
            alt=f"{short_title} 학습용 실제 지수 차트 (교육 목적 예시, 투자 권유 아님)",
        )
        if chart_html:
            chart_section = (
                '<p style="margin-top:8px;font-size:13px;color:#888;">'
                "📊 아래는 최근 실제 지수 차트입니다. 위에서 배운 개념을 직접 대입해 확인해보세요."
                "</p>" + chart_html
            )
            body = _insert_before_caution(body, chart_section)

    # 전체 조립: 배너 + 본문 + 클래스 링크 + 면책조항
    content = (
        banner_html + "\n"
        + body + "\n"
        + _CLASS_LINK + "\n"
        + _DISCLAIMER
    )

    return {
        "title":      forced_title,
        "labels":     _build_labels(topic),  # AI의 LABELS: 출력 대신 Python 고정 라벨로 덮어쓰기
        "content":    content,
        "char_count": len(content),
    }


def _insert_after_summary(body: str, key3_html: str) -> str:
    """핵심 요약 단락(두 번째 </p>) 뒤에 key3 박스를 삽입한다."""
    pattern = r'(📌 핵심 요약.+?</p>\s*<p>.+?</p>)'
    m = re.search(pattern, body, flags=re.DOTALL)
    if m:
        end = m.end()
        return body[:end] + "\n" + key3_html + body[end:]
    return key3_html + "\n" + body


def _insert_before_caution(body: str, chart_section: str) -> str:
    """'⚠️ 주의사항' 소제목 바로 앞에 참고 차트를 삽입 — 못 찾으면 본문 끝에 폴백."""
    m = re.search(r"<h[23]>\s*⚠", body)
    if m:
        return body[:m.start()] + chart_section + "\n" + body[m.start():]
    return body + "\n" + chart_section


# ── 공개 API ─────────────────────────────────────────────────────────────────

def generate_post(topic: dict, model: str = "claude-sonnet-4-6") -> dict:
    """주제 dict → Claude → {title, labels, content, char_count}"""
    news_headlines = search_topic_news(topic.get("tags", []))
    prompt  = _build_prompt(topic, news_headlines=news_headlines)
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
