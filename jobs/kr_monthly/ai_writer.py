# -*- coding: utf-8 -*-
from anthropic import Anthropic
from shared.utils import DISCLAIMER, KR_REPORT_LINKS_HTML, md_to_html, fmt_amount, apply_color_spans, fix_weekday_labels

client = Anthropic()


def _build_index_block(data: dict) -> str:
    lines = []
    for key, label in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        v = data.get(key, {})
        if not v:
            continue
        sign = "▲" if (v.get("monthly_pct") or 0) >= 0 else "▼"
        lines.append(
            f"{label}: {v['close']:,.2f}  {sign}{abs(v.get('monthly_pct') or 0):.2f}%  "
            f"(월초 종가: {v.get('month_start_close', 'N/A'):,.2f})"
        )
    return "\n".join(lines) if lines else "(지수 데이터 없음)"


def _build_best_worst_block(data: dict) -> str:
    best = data.get("best_day")
    worst = data.get("worst_day")
    lines = []
    if best:
        lines.append(f"이번 달 최고 상승일: {best['date']} ({best['pct']:+.2f}%)")
    if worst:
        lines.append(f"이번 달 최고 하락일: {worst['date']} ({worst['pct']:+.2f}%)")
    return "\n".join(lines) if lines else "(일별 등락 데이터 없음)"


def _build_stocks_block(gainers: list, losers: list) -> str:
    parts = []
    if gainers:
        parts.append("[시총 TOP10 중 월간 상승]\n" + "\n".join(
            f"  {s['name']}({s['ticker']}): +{s['change_pct']:.2f}%" for s in gainers
        ))
    if losers:
        parts.append("[시총 TOP10 중 월간 하락]\n" + "\n".join(
            f"  {s['name']}({s['ticker']}): {s['change_pct']:.2f}%" for s in losers
        ))
    return "\n".join(parts) if parts else "(종목 데이터 없음)"


def _build_investor_block(trend: dict) -> str:
    if not trend or not trend.get("days_count"):
        return "(월간 수급 데이터 없음)"
    return (
        f"이번 달 {trend['days_count']}거래일 합계 — "
        f"개인 {fmt_amount(trend['individual'])} | "
        f"외국인 {fmt_amount(trend['foreign'])} | "
        f"기관 {fmt_amount(trend['institution'])}"
    )


def _build_news_block(news: list) -> str:
    if not news:
        return "(뉴스 없음)"
    return "\n".join(f"{i + 1}. {h}" for i, h in enumerate(news[:5]))


def _build_labels(data: dict) -> list:
    """라벨을 Python에서 고정 생성 — AI의 LABELS: 출력은 신뢰하지 않고 항상 이 값으로 덮어씀."""
    return ["국내증시", "월간결산", "코스피", "코스닥", "증시리뷰", "국내월간"]


def build_prompt(data: dict, prev_issues: list = None) -> str:
    month_label = data.get("month_label", "")

    index_block = _build_index_block(data)
    best_worst_block = _build_best_worst_block(data)
    stocks_block = _build_stocks_block(data.get("top_gainers", []), data.get("top_losers", []))
    investor_block = _build_investor_block(data.get("investor_trend_monthly", {}))
    news_block = _build_news_block(data.get("news", []))

    has_stocks = bool(data.get("top_gainers") or data.get("top_losers"))
    stocks_skip_note = (
        "\n⚠️ 시총 TOP10 데이터 없음 → 아래 c) 시가총액 TOP10 월간 성적 섹션 전체 생략. 소제목 포함 텍스트 한 줄도 출력 금지. 종목명 임의 생성 절대 금지."
        if not has_stocks else ""
    )
    stocks_prompt_sec = """
c) ### 💥 시가총액 TOP10 월간 성적
   국내 시가총액 상위 10개 대형주 중 이번 달 상승·하락한 종목입니다.
   #### 📈 월간 상승 종목
   - 종목별 bullet 항목: **종목명(티커)** <span style="color:#e74c3c"><b>+X.XX%</b></span>
   #### 📉 월간 하락 종목
   - 종목별 bullet 항목: **종목명(티커)** <span style="color:#3182f6"><b>-X.XX%</b></span>
""" if has_stocks else ""

    all_labels = ",".join(_build_labels(data))

    prompt = f"""당신은 대한민국 최고의 국내 주식 시황 분석가이자 SEO 전문가입니다.
SeedUP INVEST 블로그에 올릴 국내 증시 월간 결산 포스팅을 한국어로 마크다운 형식으로 작성하세요.
블로그 설명(참고용 — 본문에 이 문장을 그대로 베끼거나 결말 인사말로 반복 출력 금지): "매달 국내 증시 한 달 흐름을 정리해 드립니다. 이번 달 핵심과 수급·주도 종목을 한눈에 확인하세요."

━━━ 국내 시장 월간 데이터 ({month_label}) ━━━

[KOSPI/KOSDAQ 월간 지수]
{index_block}

[월중 최고 상승일·최고 하락일]
{best_worst_block}

[시가총액 TOP10 월간 등락]{stocks_skip_note}
{stocks_block}

[월간 투자자별 순매수 합계]
{investor_block}

[월간 뉴스 헤드라인]
{news_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[작성 지침]
1. 위 데이터의 수치를 한 글자도 바꾸지 말 것 (환각 절대 금지)
1-1. 수급 금액 총액 언급 시 반드시 [월간 투자자별 순매수 합계] 수치만 인용. 직접 합산·추정 절대 금지.
1-2. 지수 레벨 언급 시 반드시 제공된 월간 종가·월초 종가 수치만 사용. 일중 가격·추정치 언급 절대 금지.
1-3. 시가총액 TOP10 종목의 상승·하락 이유는 뉴스 근거 없이 절대 서술하지 말 것 — 종목명과 등락률 수치만 표기.
2. 마크다운 형식, 1800~2500자
3. 단락은 2~3문장 이내로 짧게
4. 어조: 전문적이고 정중한 톤 (~입니다, ~로 분석됩니다)
5. 상승 수치는 빨간색, 하락은 파란색 인라인 스타일 적용:
   - 상승: <span style="color:#e74c3c"><b>+X.XX%</b></span>
   - 하락: <span style="color:#3182f6"><b>-X.XX%</b></span>
6. 종목 표기: **종목명(티커)** 순서로 표기
7. {{날짜}}, {{요일}} 등 중괄호 플레이스홀더 절대 출력 금지
8. 문체 규칙 (기계적 반복 금지):
   - '~로 분석됩니다', '~로 판단됩니다', '~로 보입니다'는 각각 글 전체에서 1회 이하.
   - 같은 종결어미 3문장 연속 금지 — 단, 변주는 반드시 존댓말 범위 안에서만
     (~했습니다/~입니다/~습니다 섞기, 반말체 절대 금지). 한 문단 안에 짧은 문장을 1개 이상 섞을 것.
   - 이모지는 지정된 소제목·리스트 외 본문 문장에 추가 금지.
   - '한편', '또한'으로 시작하는 문단은 2개 이하.

구조 (반드시 이 순서로, 제시된 섹션만 작성):
0) 📌 **이번 달 핵심 요약** — 아래 4가지를 3~4문장(이모티콘 제외 200~280자)으로 작성:
   - 문장 1: KOSPI·KOSDAQ 월간 등락률 수치 + 한 줄 평가
   - 문장 2: 월중 최고 상승일·최고 하락일이 있었던 배경 (데이터에서 도출되는 범위만)
   - 문장 3: 월간 수급 흐름 핵심 (개인·외국인·기관 중 어느 주체가 순매수/순매도를 주도했는지)
   - 문장 4: 다음 달 관전 포인트 한 줄 예고 — 이번 달 데이터에서 도출되는 추세만.
     데이터에 없는 구체적 일정(FOMC 등) 날짜를 추측해 넣지 말 것.

a) ### 📊 이번 달 지수 성적 ({month_label})
   - 마크다운 테이블: 지수명 | 월말 종가 | 월초 종가 | 월간 등락률 | 월간 흐름 한 줄
   - 등락률 셀에 상승/하락 색상 인라인 스타일 적용
   - 표 아래 단락 1~2개: KOSPI/KOSDAQ 흐름 차이 및 원인 서술

b) ### 📅 월중 최고 상승일·최고 하락일
   - [월중 최고 상승일·최고 하락일] 데이터를 근거로 2~3문장 서술
   - 데이터에 없는 구체적 사건을 지어내 원인으로 서술하지 말 것 — 등락 사실과 날짜만 명시
{stocks_prompt_sec}
d) ### 💰 이번 달 투자자별 매매동향
   - [월간 투자자별 순매수 합계] 데이터를 근거로 2~3문장 서술
   - 개인·외국인·기관 중 순매수 규모가 가장 큰 주체를 명시하고, 그 흐름이 지수에 미친 영향을 서술

e) ### 📰 이번 달 핵심 뉴스 & 이슈
   - 제공된 뉴스 헤드라인 번호 목록(1. 2. 3.) 3~5개 요약
   - 뉴스 없으면 이번 달 국내 시장 이슈 3개 (AI 지식 기반)

f) ### 💬 이번 달을 돌아보며
   - 3~4문장. 위 a)~e) 섹션에서 이미 다룬 수치를 반복 나열하지 말고, 이번 달
     흐름을 관통하는 해석 한 가지를 저자 관점으로 서술할 것.
   - 데이터에 없는 확신형 예측·투자 권유 문구는 금지.

g) ### 🔮 다음 달 전망
   - ⚠️ 데이터 블록에 없는 구체적 날짜·일정(경제지표 발표일, FOMC 회의일, 기업 실적
     발표일 등)을 AI 지식으로 추측해 서술하는 것 절대 금지.
   - 이번 달 데이터(지수·수급·종목 흐름)에서 직접 도출되는 추세만 2~3문장으로 전망할 것.
   - 특정 날짜·시각이 붙는 일정·이벤트명 언급 자체를 하지 말 것.

출력 형식 — 아래 헤더 뒤에 마크다운 본문만 작성 (면책 조항 포함 금지, 시스템이 자동 추가):
LABELS: {all_labels}
CONTENT:
[마크다운 본문]"""

    if prev_issues:
        lines = [f"- [{i.get('type', '')}] {i.get('description', '')}" for i in prev_issues]
        prompt += (
            "\n\n⚠️ 직전 시도에서 아래 문제로 반려됨 — 동일 실수 반복 금지, "
            "특히 데이터에 없는 구체적 사건·수치를 창작하지 말 것:\n"
            + "\n".join(lines)
        )
    return prompt


def _parse_response(raw: str, ref_date: str = "") -> dict:
    labels = []
    content_lines = []
    in_content = False
    found_content_marker = False
    labels_line_idx = None

    lines = raw.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("LABELS:"):
            labels = [l.strip() for l in line.removeprefix("LABELS:").strip().split(",") if l.strip()]
            labels_line_idx = i
        elif line.startswith("CONTENT:"):
            in_content = True
            found_content_marker = True
        elif in_content:
            content_lines.append(line)

    if not found_content_marker:
        start = labels_line_idx + 1 if labels_line_idx is not None else 0
        content_lines = lines[start:]
        print("  [파싱 경고] CONTENT: 마커 누락 — LABELS: 다음 줄부터 전체를 본문으로 대체 처리")

    md_body = "\n".join(content_lines).strip()
    if ref_date:
        md_body = fix_weekday_labels(md_body, ref_date)

    content = apply_color_spans(md_to_html(md_body)) + "\n" + DISCLAIMER + "\n" + KR_REPORT_LINKS_HTML
    return {"labels": labels, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-sonnet-4-6", prev_issues: list = None) -> dict:
    prompt = build_prompt(data, prev_issues=prev_issues)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text
    result = _parse_response(raw, data.get("month_end", ""))
    result["labels"] = _build_labels(data)
    print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")
    return result
