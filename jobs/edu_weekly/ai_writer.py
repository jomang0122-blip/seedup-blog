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
from banner import generate_banner_card, generate_key3_box, LEVEL_CONFIG
from news_search import search_topic_news
from shared.utils import extract_text
from topic_manager import peek_next
from sample_stocks import assign_sample_stock

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

_LENGTH_GUIDE = {
    # 2026-08-18 총괄 결정: 구글은 글자수를 랭킹 요소로 쓰지 않는다고 공식 확인됨
    # (John Mueller, "We don't use word count for ranking"). 상한을 정해두는 대신
    # "핵심 내용을 빠짐없이 다뤘는가"를 기준으로 삼고, 너무 부실한 글만 막는
    # 최소 하한만 둔다. 레벨 간 하한 차등은 유지(초급이 가장 짧고 고급이 가장 김).
    "초급": {"min": 1200},
    "중급": {"min": 1500},
    "고급": {"min": 1800},
}

_FORMAT_GUIDE = {
    "개념정의형": (
        "이 주제는 개념 자체를 소개하는 글입니다. 🎯 소제목에서 '~란?' 고정 패턴은 여전히 금지하되,\n"
        "'정확히 무슨 뜻일까?', '어떤 원리로 움직일까?' 등 정의를 향해 자연스럽게 파고드는 구조로 쓸 것."
    ),
    "전략활용형": (
        "이 주제는 실전에서 '어떻게 활용하는가'가 핵심입니다. 🎯 소제목부터 활용 관점으로 시작하고,\n"
        "💡 실전 활용 예시 섹션에는 반드시 판단 기준(언제 쓰고 언제 조심해야 하는지)을 구체적으로 담을 것."
    ),
    "실전가이드형": (
        "이 주제는 절차·체크리스트 성격이 강합니다. 💡 실전 활용 예시 섹션을 단계별 안내(1단계→2단계) 또는\n"
        "체크리스트 형태로 구성해 다른 주제와 톤을 구분할 것 — 단, 지정된 HTML 구조(a~e)는 그대로 유지."
    ),
    "사례분석형": (
        "이 주제는 실제 사례로 개념을 확인하는 글입니다. 🎯 소제목에서 개념을 짧게 되짚고,\n"
        "💡 실전 활용 예시 섹션은 '만약 이런 상황이라면' 식의 가정형 사례 중심으로 쓸 것(실존 기업 구체 수치 창작 금지 원칙은 동일 적용)."
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
    """라벨을 Python에서 고정 생성 — AI의 LABELS: 출력은 신뢰하지 않고 항상 이 값으로 덮어씀.

    과거 카테고리 값과 무관하게 "투자기초"를 고정으로 붙이던 버그(2026-08-18 발견) —
    카테고리별 라벨 탐색 페이지가 실제 category 값을 반영하도록 수정."""
    return ["주식투자클래스", topic["category"], topic["level"]] + topic.get("tags", [])


def _build_prompt(topic: dict, news_headlines: list = None) -> str:
    level        = topic["level"]
    title        = topic["title"]
    category     = topic["category"]
    tags         = topic["tags"]
    key_facts    = topic.get("key_facts", [])
    guide        = _LEVEL_GUIDE[level]
    format_guide = _FORMAT_GUIDE.get(topic.get("format", ""), "")
    labels       = ",".join(_build_labels(topic))
    forced_title = f"[{level}] {title}"
    short_title  = title.split("—")[0].strip()
    key_facts_block  = "\n".join(f"- {f}" for f in key_facts) if key_facts else ""
    news_block_text  = ""
    if news_headlines:
        lines = "\n".join(f"- {h}" for h in news_headlines)
        news_block_text = (
            f"\n━━━ 최신 관련 뉴스 (실제 사례로 활용 가능) ━━━\n"
            f"아래는 이 주제와 관련된 최근 뉴스 헤드라인입니다. 글에서 자연스럽게 실제 사례로 활용하세요.\n"
            f"뉴스가 직접 관련 없으면 무시하고 key_facts 기반으로만 작성하세요.\n"
            f"⚠️ 안전장치: 아래는 헤드라인 '제목'만 제공된 것이며 기사 본문은 없다. 헤드라인 문장에\n"
            f"명시되지 않은 세부 수치·날짜·인용문·후속 전개를 절대 지어내지 마라. 헤드라인에 있는\n"
            f"내용만 일반적 맥락으로 언급하고, 그 이상의 구체적 사실은 추정하지 마라.\n"
            f"{lines}\n"
        )

    length = _LENGTH_GUIDE[level]

    assigned_stock = assign_sample_stock(topic.get("id", 1))
    chart_note = (
        "\n━━━ 차트 요청 안내 ━━━\n"
        "이 글에는 총괄이 직접 캡처한 실제 차트 이미지가 나중에 삽입된다(네가 이미지를 만들지 않는다).\n"
        "너는 실제 종목·지수의 구체적 날짜·수치를 알 수 없으므로 특정 시세를 단정하지 마라.\n"
        "대신 아래 '실전 활용 예시' 섹션 끝에 어떤 차트가 필요한지 명시하는 플레이스홀더 주석을 삽입하라.\n"
        "차트-본문 일치 규칙 (필수 — 차트에만 나오고 본문엔 없는 종목명 금지, 2026-08-19 확정):\n"
        "아래 순서로 사용할 대상을 정하되, 어느 경우든 그 대상을 '실전 활용 예시' 본문에\n"
        "먼저 자연스럽게 언급한 뒤에 같은 대상으로 CHART_REQUEST를 작성하라.\n"
        "1. 위 뉴스 헤드라인을 적극적으로 훑어서, 이 글의 개념을 실제로 보여주는 실존 기업이\n"
        "   있는지 찾아라(우연히 언급되길 기다리지 말고 능동적으로 찾을 것). 있다면 그 기업을\n"
        "   실전 예시의 중심 사례로 삼아 본문에 먼저 자연스럽게 녹이고, pattern에도 명시하라.\n"
        f"2. 뉴스에 적합한 기업이 없다면 이번 글에 배정된 종목인 {assigned_stock}을(를) 써라\n"
        f"   (시가총액 상위 종목 순환배정 — 대중이 이해하기 쉽고 검색량도 많다). 가상의 예시\n"
        f"   서사(가상의 투자자 A씨 등)를 쓸 때, 처음부터 A씨가 \"{assigned_stock}에 관심이\n"
        f"   있어서/{assigned_stock} 주식을 이미 갖고 있어서/{assigned_stock}을 관심종목에\n"
        f"   등록해두고\" 같은 식으로 이 종목을 이야기의 소재로 자연스럽게 엮어라 — 이렇게 하면\n"
        f"   별도로 뜬금없는 안내 문장을 붙이지 않아도 차트가 이야기와 자연스럽게 이어진다.\n"
        f"   단, {assigned_stock}의 구체적 가격·등락률·실적 등은 지어내지 마라(실제 데이터를\n"
        f"   모르므로) — 종목명만 이야기 소재로 쓰고, 수치는 A씨의 매수 계획처럼 가상의 것만\n"
        f"   사용하라(\"A씨가 {assigned_stock}을 5주 사려고 한다\"는 가능, \"{assigned_stock}이\n"
        f"   10% 올랐다\"는 금지). 같은 종목명으로 CHART_REQUEST를 작성하라.\n"
        "3. 서로 다른 두 종목/규모를 비교해야 하거나(시총 비교, 업종 내 PER 비교 등), 지수 자체를\n"
        "   보여줘야 하는 경우(코스피 vs 코스닥 등)는 종목 하나로 대체할 수 없으므로 패턴·개념만\n"
        "   서술하라(예: '시총이 다른 두 기업 비교 개념도', '코스피·코스닥 지수 등락률 비교').\n"
        "4. 캡처 요청은 일반 차트 서비스(네이버금융 등)에서 기본으로 보이는 정보만 요구하라 —\n"
        "   배당락일 표시처럼 특별한 도구 없이는 화면에 나타나지 않는 항목을 요구하지 마라.\n"
        "5. 기본은 1개지만, 서로 다른 두 시점/두 종목을 나란히 비교해야 개념이 분명해지는\n"
        "   경우(예: 급등 전/후 비교, 종목A vs 종목B)에는 2~3개까지 요청해도 된다 — 각각\n"
        "   아래 형식 그대로 별도의 CHART_REQUEST 주석으로, 필요한 자리에 삽입하라. 근거\n"
        "   없이 개수만 늘리지 말고, 정말 여러 장이어야 이해되는 경우에만 사용할 것.\n"
        "형식(그대로 따를 것 — 여러 개면 각각 이 형식으로):\n"
        f'<!-- CHART_REQUEST pattern="[1~3 규칙에 따라 결정된 대상 — 예: {assigned_stock} 최근 3개월 '
        '이동평균선 골든크로스 구간]" period="[예: 최근 3~6개월]" '
        'note="[일반 차트 화면에 실제로 보이는 것만 — 예: 20일선이 60일선을 상향 돌파하는 지점]" -->\n'
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
{format_guide}

공통 규칙:
1. HTML 형식 (Blogger에 바로 붙여넣는 포맷)
2. 분량: 본문 텍스트 최소 {length["min"]}자 이상({level} 레벨 기준) — 상한 없음.
   글자수 자체를 목표로 삼지 말고 "핵심 내용을 빠짐없이 다뤘는가"를 기준으로 삼을 것.
   뉴스·차트·key_facts 등 근거가 있어서 자연스럽게 길어지는 건 좋으나, 근거 없이
   같은 말을 반복하거나 분량만 채우는 군더더기 문장은 금지. 🎯 개념/💡 예시/⚠️ 주의사항
   세 섹션에 고르게 배분하되, 특정 섹션에 근거(예: 차트)가 많으면 그쪽이 더 길어져도 됨.
3. 단락은 2~3문장 이내 — 모바일 가독성 우선
4. 환각 절대 금지 — 수치는 일반적으로 알려진 범위만 사용
4-1. 구체적 숫자·기준을 제시할 때 "~면 충분하다", "~하면 된다" 같은 완결형 단정 대신
     "~부터는 효과가 줄어든다", "~을 넘기면 한계가 있다"처럼 방향(상한/하한)이 분명한
     경향성 표현을 사용할 것. 특히 "N개면 충분하다"처럼 하한선인지 상한선인지 헷갈리는
     표현은 금지 — 그 숫자를 넘기면 어떻게 되는지(효과 둔화·한계 등)를 명시해 방향을
     분명히 할 것. "오늘의 핵심 N가지"(KEY3) 항목처럼 글자수 제약이 있는 자리도 이
     방향성만은 반드시 지킬 것.
4-2. 실존 기업·지수·사건에 대한 구체적 수치(등락률·금액·날짜 등)를 언급할 때는 반드시
     위 key_facts 또는 뉴스 헤드라인 블록에 명시된 내용만 사용할 것. 두 출처 어디에도
     없는 구체적 숫자는 절대 지어내지 말고, "최근", "상당폭", "일정 기간" 같은 방향성
     표현으로 대체할 것.
5. 배너 카드(글 제목 포함)는 시스템이 자동 삽입 — 본문 최상단에 글 제목을 반복 출력 금지 (소제목 h2는 아래 구조대로 출력)

[아래 a) "📌 핵심 요약" 섹션 작성 지침 — 이 지침 설명 텍스트 자체는 절대 본문에
출력하지 말 것. 실제로 출력할 것은 오직 <p> 태그 안 요약 2문장뿐이다.]
- 이 섹션은 SEO 스니펫이며 검색 결과 설명문에 그대로 노출된다.
- 첫 문장은 반드시 주제 핵심 키워드({short_title})로 시작할 것.

구조 (반드시 이 순서, 태그·이모지 변경 금지):
a) <p><strong>📌 핵심 요약</strong></p>
   <p>[이 글에서 배울 내용 2문장 — 위 지침만 따르고 괄호 설명은 출력 금지]</p>
b) <!-- KEY3_BOX -->  ← 이 주석을 핵심 요약 바로 뒤에 반드시 삽입 (변경·삭제 금지)
c) <h2>🎯 [소제목]</h2> — 개념 정의 + 왜 중요한가. 핵심 내용을 빠짐없이 다룰 것(상한 없음)
   소제목: {short_title}을 독자에게 자연스러운 한국어 문장으로 표현.
   '이란?'·'란?' 고정 패턴 절대 금지 — 주제에 맞게 자유롭게 작성.
   예) "어떤 차이가 있을까?", "왜 알아야 할까?", "어떻게 읽을까?", "어떻게 활용할까?"
d) <h2>💡 실전 활용 예시</h2> — 구체적 수치·상황 포함. 핵심 내용을 빠짐없이 다룰 것(상한 없음)
d-1) 위 차트 요청 안내에서 지정한 형식 그대로 <!-- CHART_REQUEST ... --> 주석을
     d) 섹션 안, 관련 설명 바로 뒤에 삽입 (본문에 실제 이미지·종목명을 직접 쓰지 말 것).
     보통 1개면 충분하지만, 위 규칙5에 해당하면 2~3개까지 각각 필요한 위치에 삽입 가능
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


def _generate_teaser_html(next_topic: dict | None) -> str:
    """다음 시간 예고 박스 — AI 생성이 아니라 topic_manager 큐에서 실제 다음 주제를 가져와
    시스템이 조립한다(사실과 다른 예고를 AI가 지어낼 위험을 없앰). 프롬프트 e) 섹션 주석에
    '시스템이 자동 삽입'이라고 적혀 있었으나 실제로는 구현돼 있지 않던 것을 채움(2026-08-18)."""
    if not next_topic:
        return ""
    cfg = LEVEL_CONFIG.get(next_topic["level"], LEVEL_CONFIG["초급"])
    short_title = next_topic["title"].split("—")[0].strip()
    return (
        '<div style="margin:20px 0 0 0;padding:14px 18px;background:#fafbfc;'
        f'border-radius:8px;border:1px dashed {cfg["color"]}88;'
        'font-family:-apple-system,\'Malgun Gothic\',sans-serif;">'
        f'<p style="margin:0;font-size:13px;color:#666;">🔜 다음 시간 예고: '
        f'<strong style="color:{cfg["color"]};">[{next_topic["level"]}] {short_title}</strong></p>'
        '</div>'
    )


def _style_body_tags(body: str, level: str) -> str:
    """AI가 출력한 순정 <p>/<h2>/<h3> 태그에 인라인 스타일을 입혀 다른 박스들과
    통일감을 준다. 속성 없는 태그만 매칭하므로 이미 style이 붙은 시스템 삽입
    요소(배너·KEY3박스 등)는 영향받지 않는다."""
    heading_color = LEVEL_CONFIG.get(level, LEVEL_CONFIG["초급"])["color"]
    body = re.sub(
        r"<p>",
        '<p style="font-size:15.5px;line-height:1.8;color:#333;margin:0 0 16px 0;">',
        body,
    )
    body = re.sub(
        r"<h([23])>",
        f'<h\\1 style="font-size:19px;font-weight:700;color:{heading_color};'
        'margin:32px 0 14px 0;line-height:1.4;">',
        body,
    )
    return body


def _parse_response(raw: str, topic: dict, next_topic: dict | None = None) -> dict:
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

    # 본문 문단·소제목 스타일링 — 배너·KEY3박스·차트박스·면책조항은 이미 자체 인라인
    # 스타일을 갖고 있는데, AI가 직접 쓰는 <p>/<h2>는 스타일이 전혀 없어 그 사이에서
    # 밋밋하게 튀어 가독성이 떨어지는 문제가 있었다(2026-08-18 총괄 스크린샷으로 확인).
    # 순정 태그(속성 없는 <p>, <h2>, <h3>)만 매칭하므로 이미 스타일이 붙은 시스템
    # 삽입 요소는 건드리지 않는다.
    body = _style_body_tags(body, level)

    # 핵심 박스 삽입
    banner_html = generate_banner_card(level, category, title, episode)
    key3_html   = generate_key3_box(level, key3_items) if key3_items else ""

    if "<!-- KEY3_BOX -->" in body:
        body = body.replace("<!-- KEY3_BOX -->", key3_html)
    elif key3_html:
        # 폴백: 핵심 요약 두 번째 </p> 뒤에 삽입
        body = _insert_after_summary(body, key3_html)

    # Blogger 요약 구분선(jump break) — 이게 없으면 홈/목록 화면에 이미지까지 포함된
    # 전체 본문(base64 차트 포함, 15만자 안팎)이 통째로 노출되어 다른 글들이 밀려나는
    # 문제가 있었다(2026-08-19 총괄 스크린샷으로 확인 — 홈에 글 1개만 보임).
    # 핵심요약+KEY3박스까지만 미리보기로 보이도록 그 직후에 삽입.
    if key3_html and key3_html in body:
        body = body.replace(key3_html, key3_html + "\n<!--more-->\n", 1)
    else:
        body = _insert_after_summary(body, "<!--more-->")

    # 차트 요청 플레이스홀더(<!-- CHART_REQUEST ... -->)는 여기서 처리하지 않고 본문에
    # 그대로 남겨둔다 — 총괄이 캡처한 실제 차트를 insert_chart.py가 나중에 이 자리에 삽입한다.
    # (구 chart_index 기반 자동 KS11차트 삽입은 폐기 — 2026-08-18, 모든 글에 캡처 차트로 통일)

    # 다음 시간 예고 (시스템이 실제 큐에서 가져와 조립 — AI 생성 아님)
    teaser_html = _generate_teaser_html(next_topic)

    # 전체 조립: 배너 + 본문 + 다음 시간 예고 + 클래스 링크 + 면책조항
    content = (
        banner_html + "\n"
        + body + "\n"
        + (teaser_html + "\n" if teaser_html else "")
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
    """핵심 요약 단락(두 번째 </p>) 뒤에 key3 박스를 삽입한다.

    <p[^>]*> — _style_body_tags()가 붙이는 style 속성이 있어도 매칭되도록 함
    (2026-08-18, validate_sections()와 동일한 이유로 수정)."""
    pattern = r'(📌 핵심 요약.+?</p>\s*<p[^>]*>.+?</p>)'
    m = re.search(pattern, body, flags=re.DOTALL)
    if m:
        end = m.end()
        return body[:end] + "\n" + key3_html + body[end:]
    return key3_html + "\n" + body


# ── 공개 API ─────────────────────────────────────────────────────────────────

def generate_post(topic: dict, model: str = "claude-sonnet-4-6") -> dict:
    """주제 dict → Claude → {title, labels, content, char_count}"""
    news_headlines = search_topic_news(topic.get("tags", []))
    prompt  = _build_prompt(topic, news_headlines=news_headlines)
    message = client.messages.create(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    raw    = extract_text(message)
    try:
        next_topic = peek_next(topic["id"])
    except Exception as e:
        print(f"  [경고] 다음 주제 조회 실패(예고 없이 진행): {e}")
        next_topic = None
    result = _parse_response(raw, topic, next_topic=next_topic)
    print(f"  [작성] 제목: {result['title']}")
    print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")
    return result


def review_post(topic: dict, post: dict, model: str = "claude-sonnet-4-6") -> list:
    """작성 완료된 글을 AI가 한 번 더 검토 — 총괄이 매번 전체를 다 읽지 않아도
    문제 있는 부분만 집중해서 볼 수 있도록 자체 QA 통과 여부를 반환한다
    (2026-08-18 총괄 요청: "전체 구성과 내용이 맞는지 검토하는 과정을 넣자").
    문제 없으면 빈 리스트, 있으면 지적 사항 문자열 리스트를 반환한다.
    이 검토는 본문 구조(섹션 존재 등)가 아니라 "내용이 말이 되는가"를 본다 —
    key_facts 반영 여부, 레벨 적합성, 논리적 비약·모순, 차트 요청과 본문의 일치 여부."""
    key_facts_block = "\n".join(f"- {f}" for f in topic.get("key_facts", []))
    prompt = f"""아래는 '{topic['level']}' 레벨 시드업 클래스 글의 완성본입니다. 작성자가 아니라
검토자 입장에서 냉정하게 확인해주세요.

━━━ 검증 기준 key_facts ━━━
{key_facts_block}

━━━ 완성된 글 (HTML) ━━━
{post['content']}

━━━ 검토 항목 ━━━
1. 위 key_facts가 왜곡 없이 반영됐는가 (없는 사실을 지어내지 않았는가)
2. 개념 설명 → 실전 예시 → 주의사항으로 이어지는 논리가 자연스러운가, 앞뒤 모순은 없는가
3. '{topic['level']}' 레벨 독자가 이해하기 적절한 난이도인가 (너무 쉽거나 너무 어렵지 않은가)
4. CHART_REQUEST 주석에 적힌 차트 설명이 바로 앞 본문 내용과 실제로 맞는가
5. 같은 말을 불필요하게 반복하거나, 근거 없이 분량만 채운 문장이 있는가

문제가 없으면 정확히 "문제없음" 한 단어만 출력하세요.
문제가 있으면 각 항목을 "- " 로 시작하는 줄로, 무엇이 문제인지 구체적으로 한 줄씩 적으세요.
사소하지 않은 문제만 지적하세요 — 트집 잡기 위한 지적은 하지 마세요."""

    message = client.messages.create(
        model=model,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    raw = extract_text(message).strip()
    if raw == "문제없음" or not raw:
        return []
    issues = [line.lstrip("- ").strip() for line in raw.split("\n") if line.strip().startswith("-")]
    return issues if issues else [raw]


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
