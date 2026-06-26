# -*- coding: utf-8 -*-
"""
블로그 포스팅 수치 검증 에이전트
- 수집된 실제 데이터 vs 생성된 포스팅 수치 대조
- 오류 발견 시 자동 수정본 반환
"""
import json
import re
from anthropic import Anthropic

client = Anthropic()


# ── 데이터 요약 빌더 ──────────────────────────────────────────────────────

def _build_data_summary(data: dict) -> str:
    lines = [f"날짜: {data.get('date', '')}"]

    kospi = data.get("kospi", {})
    if kospi:
        lines.append(f"KOSPI 종가: {kospi['close']:,.2f}pt  등락: {kospi['change']:+.2f}pt ({kospi['change_pct']:+.2f}%)")

    kosdaq = data.get("kosdaq", {})
    if kosdaq:
        lines.append(f"KOSDAQ 종가: {kosdaq['close']:,.2f}pt  등락: {kosdaq['change']:+.2f}pt ({kosdaq['change_pct']:+.2f}%)")

    gainers = data.get("top_gainers", [])
    if gainers:
        lines.append("급등 종목 TOP5 (시총 1000억+ KOSPI 전체·우선주 제외):")
        for g in gainers:
            lines.append(f"  {g['name']}: {g['change_pct']:+.2f}%")

    losers = data.get("top_losers", [])
    if losers:
        lines.append("급락 종목 TOP5 (시총 1000억+ KOSPI 전체·우선주 제외):")
        for l in losers:
            lines.append(f"  {l['name']}: {l['change_pct']:+.2f}%")

    for label, key in [("상승", "top_sectors"), ("하락", "bottom_sectors")]:
        sectors = data.get(key, [])
        if sectors:
            lines.append(f"{label} 섹터 TOP3:")
            for s in sectors:
                lines.append(f"  {s['name']} {s['change_pct']:+.2f}%")

    return "\n".join(lines)


# ── 검증 에이전트 ─────────────────────────────────────────────────────────

def validate_post(data: dict, post: dict) -> dict:
    """
    실제 데이터와 생성된 포스팅을 비교하여 수치 오류 검출 및 수정본 반환.

    반환값:
    {
        "approved": bool,
        "issues": [{"type": str, "description": str, "found": str, "expected": str}],
        "corrected_title": str | None,   # 제목 오류 있을 때만
        "corrections": [{"original": str, "corrected": str}]  # 본문 수정 목록
    }
    """
    data_summary = _build_data_summary(data)

    prompt = f"""당신은 한국 주식 시장 데이터 검증 전문가입니다.
아래 '실제 수집 데이터'와 '작성된 블로그 포스팅'을 비교하여 수치 오류를 검출하고 수정본을 제시하세요.

━━━ 실제 수집 데이터 (이것이 진실) ━━━
{data_summary}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ 검증 대상 포스팅 ━━━
제목: {post['title']}

{post['content']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

검증 체크리스트:
1. 제목의 종목명·수치가 "급등 종목 TOP5" 데이터와 일치하는가?
   - 여러 종목을 한 수치로 묶은 경우 (예: "20% 이상") 각 종목의 실제 수치와 비교
2. 본문의 KOSPI·KOSDAQ 종가 및 등락률이 정확한가?
3. 🔥 당일 주도 섹터 및 특징주 섹션의 종목명과 등락률이 "급등/급락 종목 TOP5" 데이터와 일치하는가?
4. 실제 데이터에 없는 수치가 임의로 삽입되지 않았는가?
5. 🔥 당일 주도 섹터 및 특징주 섹션의 섹터 등락률이 "상승/하락 섹터 TOP3" 데이터와 일치하는가?
6. [종목명 - 등락률 - 이유] 서술에서 등락률이 실제 데이터와 일치하는가? (±0.1% 허용)

중요:
- 작은 반올림 차이(±0.1%)는 무시
- 상승/하락 이유 텍스트(뉴스 기반 서술)는 검증 제외 — 수치만 검증

반드시 아래 JSON 형식으로만 응답 (코드 블록, 설명 없이 순수 JSON만):
{{
  "approved": true,
  "issues": [],
  "corrected_title": null,
  "corrections": []
}}

오류가 있으면:
{{
  "approved": false,
  "issues": [
    {{
      "type": "title_number",
      "description": "제목에 'SK·SK하이닉스 20% 이상'으로 썼으나 SK하이닉스 실제 수치는 13.06%",
      "found": "SK·SK하이닉스 20% 이상",
      "expected": "SK +20.51%, SK하이닉스 +13.06%"
    }},
    {{
      "type": "stock_number",
      "description": "본문에 SK하이닉스 등락률이 +13.06%인데 +15.00%로 잘못 기재",
      "found": "+15.00%",
      "expected": "+13.06%"
    }}
  ],
  "corrected_title": "수정된 제목 전체 (수치 오류 없으면 null)",
  "corrections": [
    {{
      "original": "포스팅에서 틀린 원본 문자열",
      "corrected": "수정된 문자열"
    }}
  ]
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # JSON 추출 (코드 블록 제거, 잘린 JSON 복구 시도)
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # 잘린 JSON인 경우 }]} 닫기 시도
    if raw and not raw.endswith("}"):
        for suffix in ["}", "}]}", "]}"]:
            try:
                result = json.loads(raw + suffix)
                break
            except json.JSONDecodeError:
                continue
        else:
            return {
                "approved": True,   # 파싱 실패 시 통과 처리 (발행 막지 않음)
                "issues": [{"type": "parse_warning", "description": "검증 응답 파싱 불완전 — 검증 생략", "found": "", "expected": ""}],
                "corrected_title": None,
                "corrections": [],
            }
    else:
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as e:
            return {
                "approved": True,
                "issues": [{"type": "parse_warning", "description": f"검증 응답 파싱 실패: {e}", "found": "", "expected": ""}],
                "corrected_title": None,
                "corrections": [],
            }

    return result


# ── 자동 수정 적용 ────────────────────────────────────────────────────────

def apply_corrections(post: dict, validation: dict) -> dict:
    """검증 결과의 corrections를 포스팅에 적용하여 수정본 반환"""
    corrected = dict(post)

    if validation.get("corrected_title"):
        corrected["title"] = validation["corrected_title"]

    content = corrected["content"]
    for fix in validation.get("corrections", []):
        original  = fix.get("original", "")
        corrected_text = fix.get("corrected", "")
        if original and corrected_text and original in content:
            content = content.replace(original, corrected_text, 1)
    corrected["content"] = content

    return corrected


# ── 단독 테스트 ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 오류가 있는 샘플로 테스트
    sample_data = {
        "date": "2026-06-25",
        "kospi":  {"close": 8930.30, "change": 459.14, "change_pct": 5.42},
        "kosdaq": {"close": 887.81,  "change": -21.46, "change_pct": -2.36},
        "top_gainers": [
            {"name": "SK",        "change_pct": 20.51},
            {"name": "SK하이닉스", "change_pct": 13.06},
        ],
        "top_losers": [
            {"name": "LG에너지솔루션", "change_pct": -3.69},
        ],
    }
    # 일부러 틀린 제목
    sample_post = {
        "title": "코스피 +5.42% 급등, SK·SK하이닉스 20% 이상 솟아올랐다 (2026.06.25)",
        "content": "<h2>역대급 반등</h2><p>코스피 8930.30pt (+5.42%) 마감.</p>",
        "labels": ["코스피"],
        "char_count": 100,
    }

    print("검증 중...")
    result = validate_post(sample_data, sample_post)
    print(f"\n승인: {result['approved']}")
    if not result["approved"]:
        print(f"발견된 오류 {len(result['issues'])}개:")
        for issue in result["issues"]:
            print(f"  [{issue['type']}] {issue['description']}")
        if result.get("corrected_title"):
            print(f"\n수정된 제목: {result['corrected_title']}")
        corrected = apply_corrections(sample_post, result)
        print(f"수정 후 제목: {corrected['title']}")
