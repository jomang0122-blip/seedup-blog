# -*- coding: utf-8 -*-
import json
import re
from anthropic import Anthropic
from shared.utils import DISCLAIMER

client = Anthropic()

_NESTED_SPAN_RE = re.compile(r'<span[^>]*>(<span[^>]*>.*?</span>)</span>')

# AI가 "왜 이 칸을 비웠는지/못 채웠는지"를 독자용 문장에 그대로 남기는 사고 패턴
# (2026-07-13 kr_daily "관련 구체적 종목명 제거 (실제 데이터 근거 부족)" 노출 실사고 확인 후 추가).
# validate_post()의 leaked_instruction 판정(AI 기반)이 놓친 경우를 잡는 결정적 2차 방어선 —
# 정규식이라 AI 호출 없이 빠르고 확실하게 걸린다. "~제거/생략 (이유)"처럼 AI 자신의
# 편집 판단을 괄호로 설명하는 특정 패턴만 좁게 잡아 정상 문장(예: "확인이 필요합니다")까지
# 오탐하지 않도록 한다. 해당 문구가 있는 표 셀은 통째로 빈 값("—")으로 교체.
_LEAKED_META_RE = re.compile(r"(관련\s*)?(구체적\s*)?종목명?\s*(제거|생략)\s*\([^)]*(근거|데이터)[^)]*\)")

# 검증 AI(validate_post)가 corrected_title에 실제 제목 대신 "제목 자체는
# 문제 없으나 본문에 오류가 있어 재검토 필요" 같은 코멘트 문장을 넣는 사고 방지용
# (2026-07-28 kr_daily 발행 글 제목이 이 코멘트로 통째로 교체된 채 발행됨 실사고
# 확인 후 추가). apply_corrections()가 corrected_title을 null 여부만 보고
# 무조건 실제 제목으로 대입해서 벌어짐 — 설명체 어미가 하나라도 있으면 의심 처리.
_TITLE_COMMENT_RE = re.compile(r"(재검토|검토\s*필요|으나|때문에|오류로\s*인해|구조적\s*오류)")

# AI에게 주는 "구글 검색 설명으로 노출됨" 같은 작성 지침 괄호가 본문에 그대로
# 남는 사고 방지용 (2026-07-20 kr_daily 발행 글에 "(구글 검색 설명으로 노출됨 —
# ...압축):" 문구가 그대로 노출된 실사고 확인 후 추가). 프롬프트 자체도 지침과
# 출력 형식을 분리하도록 고쳤지만, 이 정규식을 발행 전 최종 방어선으로 유지한다.
_LEAKED_PROMPT_INSTRUCTION_RE = re.compile(
    r"\s*\((?:구글\s*검색\s*설명|검색\s*결과\s*설명|SEO\s*스니펫)[^)]*(?:노출|압축|포함)[^)]*\)\s*:?"
)


def apply_structural_fixes(content: str, check_disclaimer: bool = True) -> tuple:
    """AI 검증(validate_post)과 별개로 Python만으로 확인 가능한 결정적 구조 결함을
    감지·자동교정한다 — AI 호출 없이 regex로 바로 판정 가능해 빠르고 확실하다.

    - 색상 span 이중중첩: apply_color_spans()가 이미 색상 span으로 감싸진 수치의
      "안쪽"만 재작성하고 바깥쪽 중복 span은 그대로 남기는 경우가 실제 발생했다
      (예: AI가 표 셀 등에서 스스로 span을 두 겹 씌운 경우). 바깥쪽을 벗겨 단일
      span만 남긴다.
    - 면책조항 누락: DISCLAIMER는 각 job의 _parse_response에서 항상 문자열로
      덧붙이지만, 과거 실제로 누락된 사례가 있어(원인 미상) 최종 방어선으로 재확인·
      재삽입한다. check_disclaimer=False면 이 검사를 건너뛴다 — edu_weekly는
      이 DISCLAIMER와 다른 자체 면책 문구(ai_writer._DISCLAIMER)를 쓰므로 그대로
      적용하면 서로 다른 두 면책조항이 중복 삽입된다.

    반환: (교정된 content, issues 목록) — issues는 validate_post()의 issue 형식과
    동일해 main.py의 validation_issues 로그에 그대로 합칠 수 있다.
    """
    issues = []
    fixed = content

    while True:
        new_fixed = _NESTED_SPAN_RE.sub(r'\1', fixed)
        if new_fixed == fixed:
            break
        fixed = new_fixed
    if fixed != content:
        issues.append({
            "type": "nested_color_span",
            "description": "색상 span 태그 이중중첩 발견 — 바깥쪽 중복 span 제거로 자동 교정",
            "found": "<span...><span...>...</span></span>",
            "expected": "<span...>...</span>",
        })

    if check_disclaimer and DISCLAIMER not in fixed:
        fixed = fixed + "\n" + DISCLAIMER
        issues.append({
            "type": "disclaimer_missing",
            "description": "면책조항이 본문에 없어 자동 재삽입",
            "found": "",
            "expected": "DISCLAIMER 블록 포함",
        })

    leaked_matches = _LEAKED_META_RE.findall(fixed)
    if leaked_matches:
        new_fixed = _LEAKED_META_RE.sub("—", fixed)
        issues.append({
            "type": "leaked_instruction_pattern",
            "description": f"AI 편집 판단 메타 문구 노출 {len(leaked_matches)}건 — 빈 값(—)으로 자동 교체",
            "found": "종목명 제거/생략 (...)",
            "expected": "—",
        })
        fixed = new_fixed

    leaked_prompt_matches = _LEAKED_PROMPT_INSTRUCTION_RE.findall(fixed)
    if leaked_prompt_matches:
        new_fixed = _LEAKED_PROMPT_INSTRUCTION_RE.sub("", fixed)
        issues.append({
            "type": "leaked_prompt_instruction",
            "description": f"프롬프트 작성 지침(구글 검색 설명 등) 노출 {len(leaked_prompt_matches)}건 — 자동 제거",
            "found": "(구글 검색 설명으로 노출됨...)",
            "expected": "(제거됨)",
        })
        fixed = new_fixed

    return fixed, issues


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z]{3,}")
# 지수 티커(KOSPI, KOSDAQ 등)는 영문 표기가 정상이므로 검사 대상에서 제외
_ALLOWED_ENGLISH = {"KOSPI", "KOSDAQ", "ETF", "TOP", "SeedUP"}


def assert_no_english_holiday_name(text: str, label: str = "휴장 안내") -> None:
    """휴장 사유·공휴일명에 영문이 섞여 발행되는 사고 재발 방지용 회로차단기
    (2026-07-17 제헌절 안내 글에 영문 휴일명이 섞여 발행돼 사용자가 직접
    한글로 수정한 사고 확인 후 추가). holidays 라이브러리가 버전에 따라
    한글/영문 어느 쪽을 반환할지 보장되지 않으므로, 원인 규명 대신 발행 직전
    결과값 자체를 검사해 영문 잔존 시 예외로 발행을 막는다.
    HTML 태그·속성(div, style 등)은 검사 대상에서 제외 — 순수 텍스트만 검사.
    """
    visible_text = _HTML_TAG_RE.sub(" ", text or "")
    hits = [w for w in _ENGLISH_WORD_RE.findall(visible_text) if w.upper() not in {a.upper() for a in _ALLOWED_ENGLISH}]
    if hits:
        raise ValueError(f"{label}에 영문 단어 잔존 — 한글 표기 필요: {hits}")


_DART_SECTION_MARK = "📋 관련 공시"


def strip_ungrounded_dart_section(content: str, dart_disclosures: dict) -> tuple:
    """본문의 '📋 관련 공시' 섹션이 실제 DART 데이터와 어긋나면 그 섹션만 제거한다.

    AI가 보고서명 표기를 미세하게 바꿔 쓸 가능성(공백·괄호 차이 등)이 있는데,
    assert_no_english_holiday_name처럼 예외를 던져 발행 전체를 막으면 공시
    섹션 하나의 표기 차이 때문에 그날 KOSPI·특징주 등 나머지 정상 내용까지
    통째로 발행이 안 되는 과함이 있다(다른 검증들은 재시도·부분교정 기회를
    주는데 이것만 즉시 차단이면 일관성도 없음). 대신 apply_structural_fixes와
    동일하게 "문제 있는 부분만 제거하고 issue로 기록, 발행은 계속" 방식으로
    완화한다 — 안전 방향(섹션 생략)은 정상 케이스와 동일한 결과이므로 이 쪽이
    더 안전하다.

    반환: (교정된 content, issues 목록) — apply_structural_fixes와 동일한 형식.
    """
    if _DART_SECTION_MARK not in content:
        return content, []

    before, _, rest = content.partition(_DART_SECTION_MARK)
    # 이 함수는 main.py에서 apply_structural_fixes() 이후(= 마크다운이 이미
    # md_to_html()로 변환된 뒤) 호출된다. 즉 구분선은 마크다운 "---"가 아니라
    # HTML "<hr/>"로 이미 바뀌어 있다 — 2026-07-29 실사고: 이 사실을 놓치고
    # "---"만 찾다 보니 매번 못 찾아 else 분기(after="")로 빠져, 공시 섹션
    # 뒤의 본문 전체(시가총액 섹션·다음 거래일 전망·면책조항)가 통째로
    # 삭제된 채 발행됨. before 쪽도 h3 태그(<h3>#### 관련 공시</h3> 변환 결과)
    # 를 함께 제거해야 헤딩 잔여물이 안 남는다.
    before = re.sub(r"<h[1-6]>\s*$", "", before)

    if "<hr/>" in rest:
        section, _, after = rest.partition("<hr/>")
        after = "<hr/>" + after
    else:
        section, after = rest, ""

    if not dart_disclosures:
        return before + after, [{
            "type": "dart_disclosure_fabricated",
            "description": "DART 데이터가 없는데 본문에 '📋 관련 공시' 섹션이 존재함 — 공시 창작 의심, 섹션 제거",
            "found": _DART_SECTION_MARK + section,
            "expected": "(섹션 제거)",
        }]

    for name, info in dart_disclosures.items():
        if name in section and info["report_nm"] not in section:
            return before + after, [{
                "type": "dart_disclosure_mismatch",
                "description": f"공시 섹션에 '{name}' 언급은 있으나 실제 보고서명('{info['report_nm']}')과 불일치 — 섹션 전체 제거",
                "found": _DART_SECTION_MARK + section,
                "expected": "(섹션 제거)",
            }]

    return content, []


def assert_market_keywords(content: str, keywords: list, label: str) -> None:
    """본문에 해당 시장 고유 키워드가 하나도 없으면 예외를 발생시킨다 —
    다른 시장(예: 미국증시) 콘텐츠가 엉뚱한 job의 제목으로 잘못 발행되는 사고의
    재발 방지용 최종 방어선이다(2026-07-02 국내데일리에 코스피 언급 0회인 글이
    발행된 사고 확인 후 추가. 코드상 재현 경로는 특정하지 못해 원인 규명 대신
    결과 기반 회로차단기로 대응한다).
    """
    if not any(kw in content for kw in keywords):
        raise ValueError(f"본문에 {label} 관련 키워드가 전혀 없음 — 다른 시장 콘텐츠 오발행 의심")


def assert_structure_complete(content: str, required_markers: list, label: str) -> None:
    """본문에 필수 섹션 마커가 모두 있는지 확인 — 하나라도 없으면 예외를 발생시킨다.

    AI 응답이 thinking 예산·max_tokens 소진으로 본문 중간에 잘리는 경우, 잘린
    본문 안의 수치만 정확하면 validate_post()의 수치 검증은 통과해버려 반토막
    글이 그대로 발행되는 사고가 있었다(2026-08-20 kr_daily 실사고: 📊1 섹션의
    표 2개만 있고 💥2·🔮3 섹션 전체와 상승/하락 특징주가 통째로 없는 글이 검증을
    통과해 발행됨). validate_post()는 "있는 내용이 정확한가"만 보고 "다 있는가"는
    보지 않으므로, 이 함수를 결과 기반 2차 방어선으로 별도 둔다.
    """
    missing = [name for name, marker in required_markers if marker not in content]
    if missing:
        raise ValueError(f"본문 구조 불완전({label}) — 누락된 섹션: {', '.join(missing)} (생성 중간에 잘렸을 가능성)")


def _build_data_summary(data: dict) -> str:
    """kr/us x daily/weekly 4종 데이터 구조를 모두 지원하는 검증용 요약."""
    lines = []

    if data.get("date"):
        lines.append(f"날짜: {data['date']}")
    if data.get("week_start"):
        lines.append(f"주간 범위: {data['week_start']} ~ {data.get('week_end', '')}")
    if data.get("us_date"):
        lines.append(f"미국 거래일: {data['us_date']}")

    # 국내 지수 — daily(change_pct) / weekly(weekly_pct) 구조 모두 처리
    for key, label in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        v = data.get(key) or {}
        if not v or v.get("close") is None:
            continue
        if v.get("change_pct") is not None:
            lines.append(f"{label} 종가: {v['close']:,.2f}pt  등락: {v.get('change', 0):+.2f}pt ({v['change_pct']:+.2f}%)")
        elif v.get("weekly_pct") is not None:
            lines.append(f"{label} 주간 종가: {v['close']:,.2f}pt  주간 등락률: {v['weekly_pct']:+.2f}%")

    # 미국 지수 (indices dict) — daily(change_pct) / weekly(weekly_pct)
    for ticker, v in (data.get("indices") or {}).items():
        pct = v.get("change_pct") if v.get("change_pct") is not None else v.get("weekly_pct")
        if v.get("close") is not None and pct is not None:
            lines.append(f"{v.get('name', ticker)} 종가: {v['close']:,.2f}  등락률: {pct:+.2f}%")

    # 미국 관심 종목 (fixed_stocks)
    fixed = data.get("fixed_stocks") or {}
    if fixed:
        lines.append("관심 종목:")
        for t, v in fixed.items():
            pct = v.get("change_pct") if v.get("change_pct") is not None else v.get("weekly_pct")
            if v.get("close") is not None and pct is not None:
                lines.append(f"  {t} {v['name']}: ${v['close']:,.2f} ({pct:+.2f}%)")
            else:
                lines.append(f"  {t} {v['name']}: 데이터 없음 (본문에는 '확인 불가'로 표기되어야 정상)")

    # 급등락 종목 — kr(top_gainers/losers: name) / us(top_movers: ticker)
    gainers = data.get("top_gainers", [])
    if gainers:
        lines.append("급등 종목:")
        for g in gainers:
            lines.append(f"  {g['name']}: {g['change_pct']:+.2f}%")

    losers = data.get("top_losers", [])
    if losers:
        lines.append("급락 종목:")
        for l in losers:
            lines.append(f"  {l['name']}: {l['change_pct']:+.2f}%")

    movers = data.get("top_movers", [])
    if movers:
        lines.append("급등락 종목 (워치리스트):")
        for m in movers:
            pct = m.get("change_pct") if m.get("change_pct") is not None else m.get("weekly_pct")
            lines.append(f"  {m['ticker']}({m.get('name', '')}): {pct:+.2f}%")

    # marketcap_top은 get_marketcap_top_stocks()에서 네이버 재검증까지 거친
    # 최종값이다 — 아래 stock_pct_map(FDR 원본, 장마감 직후 반영지연 가능)과
    # 별개로 반드시 노출해야, 검증 AI가 이미 정확히 교정된 본문 수치를 구버전
    # 원본과 대조해 "오류"로 오판하는 사고를 막을 수 있다(2026-07-29 실사고:
    # SK하이닉스 marketcap_top -9.61%(교정된 정답)를 stock_pct_map -2.26%
    # (지연된 FDR 원본)와 비교해 되레 정답을 오답으로 자동교정할 뻔함).
    marketcap_top = data.get("marketcap_top", [])
    if marketcap_top:
        lines.append("시가총액 상위 종목 (네이버 재검증 완료 — 이 수치가 최종 정답):")
        for s in marketcap_top:
            lines.append(f"  {s['name']}: {s['change_pct']:+.2f}%")

    for label, key in [("상승", "top_sectors"), ("하락", "bottom_sectors")]:
        sectors = data.get(key, [])
        if sectors:
            lines.append(f"{label} 섹터 TOP3:")
            for s in sectors:
                line = f"  {s['name']} {s['change_pct']:+.2f}%"
                breadth = s.get("breadth")
                if breadth:
                    line += f" (업종폭: {breadth['total']}종목 중 {breadth['same_dir']}개 동방향)"
                lines.append(line)

    news_headlines = data.get("crawled_news_features", [])
    stock_pct_map = data.get("stock_pct_map", {})
    if news_headlines and stock_pct_map:
        lines.append("뉴스 기반 주요 종목 실제 등락률:")
        for h in news_headlines:
            for name, pct in stock_pct_map.items():
                if name in h:
                    lines.append(f"  {name}: {pct:+.2f}%")
                    break

    dart_disclosures = data.get("dart_disclosures", {})
    if dart_disclosures:
        lines.append("DART 공시 및 관련뉴스:")
        for name, info in dart_disclosures.items():
            line = f"  {name}: {info.get('report_nm', '')} (접수 {info.get('rcept_dt', '')})"
            if info.get("news"):
                line += f" [관련뉴스: {info['news']}]"
            lines.append(line)

    return "\n".join(lines)


def validate_post(data: dict, post: dict) -> dict:
    data_summary = _build_data_summary(data)

    prompt = f"""당신은 주식 시장 데이터 검증 전문가입니다.
아래 '실제 수집 데이터'와 '작성된 블로그 포스팅'을 비교하여 수치 오류를 검출하고 수정본을 제시하세요.

━━━ 실제 수집 데이터 (이것이 진실) ━━━
{data_summary}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ 검증 대상 포스팅 ━━━
제목: {post['title']}

{post['content']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

검증 체크리스트:
1. 제목의 종목명·수치가 데이터와 일치하는가?
2. 본문의 지수(KOSPI·KOSDAQ 또는 나스닥·S&P500·다우) 종가 및 등락률이 정확한가?
3. 종목 섹션(특징주·관심 종목·급등락)의 종목명·등락률이 데이터와 일치하는가?
4. 섹터 등락률이 데이터와 일치하는가? (섹터 데이터가 있는 경우만)
5. 본문에 "N종목 중 M개" 형태의 업종폭 수치가 있으면 해당 섹터의 (업종폭: ...) 데이터와
   정확히 일치하는가? — 인접 섹터의 수치를 잘못 옮겨 적는 오류가 실제 발생함
6. 본문에 서술된 구체적 사건(예: "OO ETF 편입", "OO와 계약 체결", "OO 발표")이
   위 실제 수집 데이터(뉴스 헤드라인 포함)에 실제로 근거가 있는가? 데이터에 없는
   구체적 사건을 지어내 서술한 경우 "news_fabrication" 타입으로 보고할 것.
   (일반적인 시황 해설·추세 서술은 대상 아님 — 뉴스 헤드라인에 없는데 마치
   실제 발표·계약처럼 구체적으로 서술한 경우만 해당)
7. 동일 종목 + 동일 재료(예: "브로드컴-애플 계약")가 서로 다른 섹션(핵심요약,
   표 아래 단락, 급등락 종목, 핵심 뉴스 등)에서 3회 이상 반복 서술되는가?
   반복되면 "content_repetition" 타입으로 보고할 것.
8. 본문 문장 안에 AI 작성 지침이 실수로 그대로 출력된 부분이 있는가?
   (예: "(뉴스 근거 없는 이유 작성 금지 — 수치만 표기)"처럼, 독자에게 불필요한
   지시문·메타 설명이 괄호 등에 담겨 문장에 섞여 있는 경우. "공매도 금지",
   "매매 금지 종목"처럼 실제 금융 용어로서 "금지"가 쓰인 경우는 해당 없음 —
   AI 자신에게 내리는 작성 지시로 읽히는 문구만 해당.)
   있으면 "leaked_instruction" 타입으로 보고하고, 해당 문구를 제거한 문장을
   "corrections"에 담을 것(needs_regenerate는 별도 처리 불필요).
9. 섹터·종목 표에서 특정 칸(예: 대표종목)이 비어있거나 "—"/데이터없음 처리되어
   있는데, 같은 행 또는 근처의 다른 서술 문장(예: "핵심 흐름 한 줄")에는 구체적인
   종목명이 언급되는 모순이 있는가? (예: 대표종목 칸은 비어있는데 설명 문장에는
   "코웨이 등 소수 종목이" 처럼 종목명이 등장) — 대표종목 칸을 비운 이유가 데이터
   부재라면 그 종목명이 다른 곳에도 나타나서는 안 된다. 있으면 "field_narrative_mismatch"
   타입으로 보고하고, 해당 종목명을 "소수 종목", "일부 종목" 등 일반화된 표현으로
   바꾼 문장을 "corrections"에 담을 것.

중요:
- 작은 반올림 차이(±0.1%)는 무시
- 상승/하락 이유 텍스트의 표현 방식 자체는 검증 제외 — 사실 근거 유무(6번)와 반복 여부(7번)만 검증

반드시 아래 JSON 형식으로만 응답 (코드 블록, 설명 없이 순수 JSON만):
{{
  "approved": true,
  "issues": [],
  "corrected_title": null,
  "corrections": [],
  "needs_regenerate": false
}}

오류가 있으면:
{{
  "approved": false,
  "issues": [
    {{
      "type": "title_number",
      "description": "설명",
      "found": "틀린 값",
      "expected": "올바른 값"
    }}
  ],
  "corrected_title": "수정된 제목 (오류 없으면 null)",
  "corrections": [
    {{
      "original": "틀린 원본 문자열",
      "corrected": "수정된 문자열"
    }}
  ],
  "needs_regenerate": false
}}

"issues"에 type이 "news_fabrication" 또는 "content_repetition"인 항목이 하나라도 있으면
"needs_regenerate"를 반드시 true로 설정할 것 (문자열 치환으로 고칠 수 없는 구조적 문제이므로
글 자체를 재생성해야 함). 그 외 수치 오류만 있으면 needs_regenerate는 false로 유지."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    if raw and not raw.endswith("}"):
        for suffix in ["}", "}]}", "]}"]:
            try:
                return json.loads(raw + suffix)
            except json.JSONDecodeError:
                continue
        return {
            "approved": True,
            "issues": [{"type": "parse_warning", "description": "검증 응답 파싱 불완전 — 검증 생략", "found": "", "expected": ""}],
            "corrected_title": None,
            "corrections": [],
            "needs_regenerate": False,
        }

    try:
        result = json.loads(raw)
        result.setdefault("needs_regenerate", False)
        return result
    except json.JSONDecodeError as e:
        return {
            "approved": True,
            "issues": [{"type": "parse_warning", "description": f"검증 응답 파싱 실패: {e}", "found": "", "expected": ""}],
            "corrected_title": None,
            "corrections": [],
            "needs_regenerate": False,
        }


def apply_corrections(post: dict, validation: dict) -> dict:
    """검증 결과를 반영. 제목은 corrected_title로 교체하고,
    본문은 corrections(원본→수정 문자열) 중 원본이 본문에 정확히 1번만 등장하는
    항목만 치환한다. 본문에 0번 또는 2번 이상 등장하는 항목은 건너뛴다
    (AI가 원문을 잘못 짚었거나, 다른 종목·섹터가 우연히 같은 문자열을 가진
    경우까지 전역 치환되어 엉뚱한 곳이 바뀌는 사고 방지) — 원본이 1번만
    등장할 때는 길이가 길어도(뉴스 창작 문장 전체 삭제 등) 그 유일한
    등장 위치만 안전하게 치환되므로 길이 제한을 두지 않는다.
    발행을 막는 대신 본문을 고쳐서 그대로 발행."""
    corrected = dict(post)
    new_title = validation.get("corrected_title")
    if new_title:
        if len(new_title) > 80 or _TITLE_COMMENT_RE.search(new_title):
            print(f"  [경고] corrected_title이 설명 문구로 의심되어 제목 교체 건너뜀: {new_title!r}")
        else:
            corrected["title"] = new_title

    content = corrected.get("content", "")
    applied, skipped = [], []
    for c in validation.get("corrections") or []:
        original = (c or {}).get("original")
        fixed = (c or {}).get("corrected")
        if not original or not fixed:
            continue
        if content.count(original) != 1:
            skipped.append(original)
            continue
        content = content.replace(original, fixed, 1)
        applied.append(original)

    corrected["content"] = content
    if "char_count" in corrected:
        corrected["char_count"] = len(content)
    corrected["_correction_log"] = {"applied": applied, "skipped": skipped}
    return corrected
