# -*- coding: utf-8 -*-
import json
import re
from anthropic import Anthropic

client = Anthropic()


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
        lines.append("급등 종목 TOP5 (시총 1조+ KOSPI·우선주 제외):")
        for g in gainers:
            lines.append(f"  {g['name']}: {g['change_pct']:+.2f}%")

    losers = data.get("top_losers", [])
    if losers:
        lines.append("급락 종목 TOP5 (시총 1조+ KOSPI·우선주 제외):")
        for l in losers:
            lines.append(f"  {l['name']}: {l['change_pct']:+.2f}%")

    for label, key in [("상승", "top_sectors"), ("하락", "bottom_sectors")]:
        sectors = data.get(key, [])
        if sectors:
            lines.append(f"{label} 섹터 TOP3:")
            for s in sectors:
                lines.append(f"  {s['name']} {s['change_pct']:+.2f}%")

    news_headlines = data.get("crawled_news_features", [])
    stock_pct_map = data.get("stock_pct_map", {})
    if news_headlines and stock_pct_map:
        lines.append("뉴스 기반 주요 종목 실제 등락률:")
        for h in news_headlines:
            for name, pct in stock_pct_map.items():
                if name in h:
                    lines.append(f"  {name}: {pct:+.2f}%")
                    break

    return "\n".join(lines)


def validate_post(data: dict, post: dict) -> dict:
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
1. 제목의 종목명·수치가 데이터와 일치하는가?
2. 본문의 KOSPI·KOSDAQ 종가 및 등락률이 정확한가?
3. 특징주 섹션의 종목명·등락률이 데이터와 일치하는가?
4. 섹터 등락률이 데이터와 일치하는가?

중요:
- 작은 반올림 차이(±0.1%)는 무시
- 상승/하락 이유 텍스트는 검증 제외 — 수치만 검증

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
  ]
}}"""

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
        }

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        return {
            "approved": True,
            "issues": [{"type": "parse_warning", "description": f"검증 응답 파싱 실패: {e}", "found": "", "expected": ""}],
            "corrected_title": None,
            "corrections": [],
        }


def apply_corrections(post: dict, validation: dict) -> dict:
    corrected = dict(post)

    if validation.get("corrected_title"):
        corrected["title"] = validation["corrected_title"]

    content = corrected["content"]
    for fix in validation.get("corrections", []):
        original = fix.get("original", "")
        corrected_text = fix.get("corrected", "")
        if original and corrected_text and original in content:
            content = content.replace(original, corrected_text, 1)
    corrected["content"] = content

    return corrected
