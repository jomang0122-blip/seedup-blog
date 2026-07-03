# -*- coding: utf-8 -*-
from anthropic import Anthropic
from shared.utils import DISCLAIMER, md_to_html, fmt_amount, apply_color_spans, fix_weekday_labels, us_time_rule_block

client = Anthropic()


def _build_index_block(data: dict) -> str:
    lines = []
    for key, label in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        v = data.get(key, {})
        if not v:
            continue
        sign = "▲" if (v.get("weekly_pct") or 0) >= 0 else "▼"
        lines.append(
            f"{label}: {v['close']:,.2f}  {sign}{abs(v.get('weekly_pct') or 0):.2f}%  "
            f"(이전 금요일 종가: {v.get('prev_close', 'N/A'):,.2f})"
        )
    return "\n".join(lines) if lines else "(지수 데이터 없음)"


def _build_investor_block(investor_top3: dict) -> str:
    if not investor_top3:
        return "(수급 데이터 없음)"
    lines = []
    for label in ["외국인", "기관"]:
        v = investor_top3.get(label, {})
        buy3  = v.get("buy", [])
        sell3 = v.get("sell", [])
        buy_str  = ", ".join(f"{s['name']}({fmt_amount(s['net_amount'])})" for s in buy3)  if buy3  else "-"
        sell_str = ", ".join(f"{s['name']}({fmt_amount(s['net_amount'])})" for s in sell3) if sell3 else "-"
        lines.append(f"{label} 주간 순매수: {buy_str} | 순매도: {sell_str}")
    return "\n".join(lines)


def _build_stocks_block(gainers: list, losers: list) -> str:
    parts = []
    if gainers:
        parts.append("[주간 급등 TOP5]\n" + "\n".join(
            f"  {s['name']}({s['ticker']}): +{s['change_pct']:.2f}%" for s in gainers
        ))
    if losers:
        parts.append("[주간 급락 TOP5]\n" + "\n".join(
            f"  {s['name']}({s['ticker']}): {s['change_pct']:.2f}%" for s in losers
        ))
    return "\n".join(parts) if parts else "(종목 데이터 없음)"


def _build_sector_block(top_sectors: list, bottom_sectors: list) -> str:
    lines = []
    if top_sectors:
        lines.append("[주간 강세 섹터] " + ", ".join(
            f"{s['name']}({s['change_pct']:+.2f}%)" for s in top_sectors
        ))
    if bottom_sectors:
        lines.append("[주간 약세 섹터] " + ", ".join(
            f"{s['name']}({s['change_pct']:+.2f}%)" for s in bottom_sectors
        ))
    return "\n".join(lines) if lines else "(섹터 데이터 없음)"


def _build_news_block(news: list) -> str:
    if not news:
        return "(뉴스 없음)"
    return "\n".join(f"{i + 1}. {h}" for i, h in enumerate(news[:5]))


def _date_range_kor(week_start: str, week_end: str) -> str:
    """'2026-06-23' ~ '2026-06-27' → '6월 23일~27일'"""
    try:
        from datetime import datetime as _dt
        s = _dt.strptime(week_start, "%Y-%m-%d")
        e = _dt.strptime(week_end, "%Y-%m-%d")
        if s.month == e.month:
            return f"{s.month}월 {s.day}일~{e.day}일"
        return f"{s.month}월 {s.day}일~{e.month}월 {e.day}일"
    except Exception:
        return f"{week_start}~{week_end}"


def _next_week_str(week_end: str) -> str:
    """다음 주 월~금 날짜 범위 문자열."""
    try:
        from datetime import datetime as _dt, timedelta
        end      = _dt.strptime(week_end, "%Y-%m-%d")
        next_mon = end + timedelta(days=3)
        next_fri = end + timedelta(days=7)
        return f"{next_mon.month}월 {next_mon.day}일~{next_fri.day}일"
    except Exception:
        return "다음 주"


def build_prompt(data: dict) -> str:
    week_start = data.get("week_start", "")
    week_end   = data.get("week_end", "")
    date_range = _date_range_kor(week_start, week_end)
    next_week  = _next_week_str(week_end)

    index_block   = _build_index_block(data)
    stocks_block  = _build_stocks_block(data.get("top_gainers", []), data.get("top_losers", []))
    sector_block  = _build_sector_block(data.get("top_sectors", []), data.get("bottom_sectors", []))
    news_block    = _build_news_block(data.get("news", []))
    time_rule_block = us_time_rule_block(week_end)

    investor_top3  = data.get("investor_top3", {})
    investor_block = _build_investor_block(investor_top3)
    # 실제 buy/sell 데이터가 하나라도 있어야 섹션 포함
    has_investor   = any(
        v.get("buy") or v.get("sell")
        for v in investor_top3.values()
    ) if investor_top3 else False
    investor_data_sec = f"\n[메이저 수급 (주간 합산 TOP3)]\n{investor_block}\n" if has_investor else ""
    investor_prompt_sec = """
b) ### 💰 메이저 수급 흐름 (주간)
   - 마크다운 테이블: 투자 주체 | 주간 순매수 TOP3 | 주간 순매도 TOP3
   - 표 아래 단락 1개: 외국인·기관 수급 방향 해석
""" if has_investor else ""

    base_labels   = ["국내증시", "코스피", "위클리", "주간시황", "코스닥", "증시리뷰"]
    sector_labels = [s["name"] for s in data.get("top_sectors", [])[:2]]
    stock_labels  = [s["name"] for s in data.get("top_gainers", [])[:2]]
    all_labels    = ",".join(base_labels + sector_labels + stock_labels)

    return f"""당신은 대한민국 최고의 국내 주식 시황 분석가이자 SEO 전문가입니다.
SeedUP INVEST 블로그에 올릴 국내 증시 주간 시황 포스팅을 한국어로 마크다운 형식으로 작성하세요.
블로그 설명: "매주 국내 증시 주간 흐름을 정리해 드립니다. 이번 주 핵심과 수급·섹터 흐름을 한눈에 확인하세요."

━━━ 국내 시장 주간 데이터 ({week_start} ~ {week_end}) ━━━

[KOSPI/KOSDAQ 주간 지수]
{index_block}
{investor_data_sec}
[주간 급등락 종목]
{stocks_block}

[주간 섹터 등락률]
{sector_block}

[주간 뉴스 헤드라인]
{news_block}

[시간 변환 규칙 — 미국 일정(FOMC 등) 시각 언급 시 반드시 이 규칙만 사용]
{time_rule_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[작성 지침]
1. 위 데이터의 수치를 한 글자도 바꾸지 말 것 (환각 절대 금지)
2. 마크다운 형식, 2000~2800자
3. 단락은 2~3문장 이내로 짧게
4. 어조: 전문적이고 정중한 톤 (~입니다, ~로 분석됩니다)
5. 상승 수치는 빨간색, 하락은 파란색 인라인 스타일 적용:
   - 상승: <span style="color:#e74c3c"><b>+X.XX%</b></span>
   - 하락: <span style="color:#3182f6"><b>-X.XX%</b></span>
6. 종목 표기: **종목명(티커)** 순서로 표기 (예: **삼성전자(005930)**)
7. 이모티콘 규칙: 급등락 항목 문두에 상승 📈, 하락 📉 반드시 삽입
8. {{날짜}}, {{요일}} 등 중괄호 플레이스홀더 절대 출력 금지

구조 (반드시 이 순서로, 제시된 섹션만 작성):
0) 📌 **이번 주 핵심 요약** (구글 검색 설명으로 노출됨 — KOSPI·KOSDAQ 주간 등락률·주요 섹터·핵심 이슈를 첫 2문장 안에 반드시 포함. 이모티콘 제외 150자 이내로 압축)

a) ### 📊 주간 시장 지표 ({date_range})
   - 마크다운 테이블: 지수명 | 주간 종가 | 이전 종가 | 주간 등락률 | 주간 흐름 한 줄
   - 등락률 셀에 상승/하락 색상 인라인 스타일 적용
   - 표 아래 단락 1~2개: KOSPI/KOSDAQ 흐름 차이 및 원인 서술
{investor_prompt_sec}
c) ### 💥 이번 주 급등락 종목
   #### 📈 주간 급등 종목
   - 종목별 bullet 항목: **종목명(티커)** <span style="color:#e74c3c"><b>+X.XX%</b></span> — 이유 한 줄
   #### 📉 주간 급락 종목
   - 종목별 bullet 항목: **종목명(티커)** <span style="color:#3182f6"><b>-X.XX%</b></span> — 이유 한 줄

d) ### 🏭 주간 주도·약세 섹터
   - 마크다운 테이블: 구분 | 섹터명 | 등락률 | 대표 이슈
   - 표 아래 단락 1개: 섹터 흐름 해석

e) ### 📰 이번 주 핵심 뉴스 & 이슈
   - 제공된 뉴스 헤드라인 번호 목록(1. 2. 3.) 3~5개 요약
   - 뉴스 없으면 이번 주 국내 시장 이슈 3개 (AI 지식 기반)

f) ### 🔮 다음 주 전망 및 주목 일정(한국시간) ({next_week})
   - 경제지표 발표, 기업 실적, FOMC 이슈 등 1~3개 (AI 지식 기반)
   - 모든 시각은 반드시 한국시간(KST) 기준으로 표기 (예: 7월 1일(화) 한국시간 09:00)
   - 미국 일정의 한국시간 변환은 [시간 변환 규칙] 블록의 시차만 사용 — 직접 계산 금지
   - 플레이스홀더 금지 — 날짜/일정을 모르면 지표명만 작성

출력 형식 — 아래 헤더 뒤에 마크다운 본문만 작성 (면책 조항 포함 금지, 시스템이 자동 추가):
LABELS: {all_labels}
CONTENT:
[마크다운 본문]"""


def _parse_response(raw: str, ref_date: str = "") -> dict:
    labels        = []
    content_lines = []
    in_content    = False

    for line in raw.split("\n"):
        if line.startswith("LABELS:"):
            labels = [l.strip() for l in line.removeprefix("LABELS:").strip().split(",") if l.strip()]
        elif line.startswith("CONTENT:"):
            in_content = True
        elif in_content:
            content_lines.append(line)

    md_body = "\n".join(content_lines).strip()
    if ref_date:
        md_body = fix_weekday_labels(md_body, ref_date)

    content = apply_color_spans(md_to_html(md_body)) + "\n" + DISCLAIMER
    return {"labels": labels, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-haiku-4-5-20251001") -> dict:
    prompt  = build_prompt(data)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw    = message.content[0].text
    result = _parse_response(raw, data.get("week_end", ""))
    print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")
    return result
