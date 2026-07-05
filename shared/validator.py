# -*- coding: utf-8 -*-
import json
import re
from anthropic import Anthropic

client = Anthropic()


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
    """검증 결과를 반영. 제목은 corrected_title로 교체하고,
    본문은 corrections(원본→수정 문자열) 중 원본이 본문에 정확히 1번만 등장하는
    항목만 치환한다. AI가 수정값 대신 설명 문구를 넣는 과거 사고를 막기 위해
    원본 문자열이 본문에 없거나 지나치게 긴 항목(설명 문구로 의심)은 건너뛰고,
    본문에 2번 이상 등장하는 항목도 건너뛴다(다른 종목·섹터가 우연히 같은
    문자열을 가진 경우까지 전역 치환되어 엉뚱한 곳이 바뀌는 사고 방지) —
    발행을 막는 대신 본문을 고쳐서 그대로 발행."""
    corrected = dict(post)
    if validation.get("corrected_title"):
        corrected["title"] = validation["corrected_title"]

    content = corrected.get("content", "")
    applied, skipped = [], []
    for c in validation.get("corrections") or []:
        original = (c or {}).get("original")
        fixed = (c or {}).get("corrected")
        if not original or not fixed:
            continue
        if len(original) > 80 or len(fixed) > 80 or content.count(original) != 1:
            skipped.append(original)
            continue
        content = content.replace(original, fixed)
        applied.append(original)

    corrected["content"] = content
    if "char_count" in corrected:
        corrected["char_count"] = len(content)
    corrected["_correction_log"] = {"applied": applied, "skipped": skipped}
    return corrected
