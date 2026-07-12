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
        sign = "▲" if (v.get("weekly_pct") or 0) >= 0 else "▼"
        lines.append(
            f"{label}: {v['close']:,.2f}  {sign}{abs(v.get('weekly_pct') or 0):.2f}%  "
            f"(이전 금요일 종가: {v.get('prev_close', 'N/A'):,.2f})"
        )
    return "\n".join(lines) if lines else "(지수 데이터 없음)"


def _build_market_trend_block(market_trend: list) -> str:
    if not market_trend:
        return "(일별 수급 데이터 없음)"
    lines = []
    total_ind = total_for = total_ins = 0
    for r in market_trend:
        kospi_str = f"{r['kospi_pct']:+.2f}%" if r.get("kospi_pct") is not None else "확인불가"
        lines.append(
            f"{r['date']}({r['weekday']}): 코스피 {kospi_str} | "
            f"개인 {fmt_amount(r['individual'], force_eok=True)} | "
            f"외국인 {fmt_amount(r['foreign'], force_eok=True)} | "
            f"기관 {fmt_amount(r['institution'], force_eok=True)}"
        )
        total_ind += r.get("individual", 0)
        total_for += r.get("foreign", 0)
        total_ins += r.get("institution", 0)
    lines.append(
        f"[주간합계]: 개인 {fmt_amount(total_ind)} | "
        f"외국인 {fmt_amount(total_for)} | 기관 {fmt_amount(total_ins)}"
    )
    return "\n".join(lines)


def _build_stocks_block(gainers: list, losers: list) -> str:
    """시가총액 상위 10종목 중 이번 주 상승/하락한 종목 (data_collector.get_top_stocks_weekly)."""
    parts = []
    if gainers:
        parts.append("[시총 TOP10 중 주간 상승]\n" + "\n".join(
            f"  {s['name']}({s['ticker']}): +{s['change_pct']:.2f}%" for s in gainers
        ))
    if losers:
        parts.append("[시총 TOP10 중 주간 하락]\n" + "\n".join(
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
    """다음 주 월~금 날짜 범위 문자열.

    현재 kr_weekly의 week_end는 get_week_dates()가 순수 달력 계산으로 만든
    진짜 금요일이라 +3일/+7일 계산이 항상 안전하지만, us_weekly에서 같은
    가정이 "그 주 실제 마지막 거래일" 방식으로 바뀌며 깨진 사고가 있었다
    (금요일이 공휴일이면 week_end가 금요일이 아니게 됨 → 날짜가 틀어짐).
    kr_weekly가 나중에 같은 방식으로 바뀌어도 안전하도록 요일 무관 계산으로
    미리 통일해둔다.
    """
    try:
        from datetime import datetime as _dt, timedelta
        end = _dt.strptime(week_end, "%Y-%m-%d")
        days_to_next_monday = (7 - end.weekday()) % 7 or 7
        next_mon = end + timedelta(days=days_to_next_monday)
        next_fri = next_mon + timedelta(days=4)
        return f"{next_mon.month}월 {next_mon.day}일~{next_fri.day}일"
    except Exception:
        return "다음 주"


def _build_labels(data: dict) -> list:
    """라벨을 Python에서 고정 생성 — AI의 LABELS: 출력은 신뢰하지 않고 항상 이 값으로 덮어씀."""
    base_labels   = ["국내증시", "코스피", "위클리", "주간시황", "코스닥", "증시리뷰", "국내위클리"]
    sector_labels = [s["name"] for s in data.get("top_sectors", [])[:2]]
    stock_labels  = [s["name"] for s in data.get("top_gainers", [])[:2]]
    return base_labels + sector_labels + stock_labels


def build_prompt(data: dict) -> str:
    week_start = data.get("week_start", "")
    week_end   = data.get("week_end", "")
    date_range = _date_range_kor(week_start, week_end)
    next_week  = _next_week_str(week_end)

    index_block   = _build_index_block(data)
    stocks_block  = _build_stocks_block(data.get("top_gainers", []), data.get("top_losers", []))
    sector_block  = _build_sector_block(data.get("top_sectors", []), data.get("bottom_sectors", []))
    news_block    = _build_news_block(data.get("news", []))

    market_trend      = data.get("market_trend", [])
    market_trend_block = _build_market_trend_block(market_trend)
    has_market_trend  = bool(market_trend)
    investor_data_sec = f"\n[코스피 시장 전체 일별 투자자별 순매수 (억원 단위, 개인/외국인/기관)]\n{market_trend_block}\n" if has_market_trend else ""
    investor_prompt_sec = """
b) ### 💰 이번 주 코스피 투자자별 매매동향
   - 마크다운 테이블: 날짜(요일) | 코스피 등락률 | 개인 순매수 | 외국인 순매수 | 기관 순매수
   - 데이터 블록의 5개 거래일을 월~금 순서대로 빠짐없이 모두 표에 포함 (임의 삭제·재배열 금지)
   - 표 마지막 행에 **주간 합계** 행 추가: 데이터 블록의 [주간합계] 수치 그대로 사용 (코스피 등락률 칸은 "-" 표기)
   - 등락률 셀에만 상승/하락 색상 인라인 스타일 적용 (순매수 금액엔 색상 적용 금지)
   - 표 아래 단락 1~2개: 요일별 수급 방향과 코스피 등락률의 상관관계 해석
     (예: 기관 순매수가 강했던 날 코스피 상승폭이 확대됐는지 등, 데이터에서 직접 드러나는 패턴만 서술)
""" if has_market_trend else ""

    has_stocks = bool(data.get("top_gainers") or data.get("top_losers"))
    stocks_skip_note = (
        "\n⚠️ 시총 TOP10 데이터 없음 → 아래 c) 시가총액 TOP10 주간 성적 섹션 전체 생략. 소제목 포함 텍스트 한 줄도 출력 금지. 종목명 임의 생성 절대 금지."
        if not has_stocks else ""
    )
    stocks_prompt_sec = """
c) ### 💥 시가총액 TOP10 주간 성적
   국내 시가총액 상위 10개 대형주 중 이번 주 상승·하락한 종목입니다.
   #### 📈 주간 상승 종목
   - 종목별 bullet 항목: **종목명(티커)** <span style="color:#e74c3c"><b>+X.XX%</b></span>
   #### 📉 주간 하락 종목
   - 종목별 bullet 항목: **종목명(티커)** <span style="color:#3182f6"><b>-X.XX%</b></span>
""" if has_stocks else ""

    all_labels    = ",".join(_build_labels(data))

    return f"""당신은 대한민국 최고의 국내 주식 시황 분석가이자 SEO 전문가입니다.
SeedUP INVEST 블로그에 올릴 국내 증시 주간 시황 포스팅을 한국어로 마크다운 형식으로 작성하세요.
블로그 설명(참고용 — 본문에 이 문장을 그대로 베끼거나 결말 인사말로 반복 출력 금지): "매주 국내 증시 주간 흐름을 정리해 드립니다. 이번 주 핵심과 수급·섹터 흐름을 한눈에 확인하세요."

━━━ 국내 시장 주간 데이터 ({week_start} ~ {week_end}) ━━━

[KOSPI/KOSDAQ 주간 지수]
{index_block}
{investor_data_sec}
[시가총액 TOP10 주간 등락]{stocks_skip_note}
{stocks_block}

[주간 섹터 등락률]
{sector_block}

[주간 뉴스 헤드라인]
{news_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[작성 지침]
1. 위 데이터의 수치를 한 글자도 바꾸지 말 것 (환각 절대 금지)
1-1. 수급 금액 총액 언급 시 반드시 데이터 블록의 [주간합계] 수치만 인용. 직접 합산·추정 절대 금지.
1-2. 지수 레벨(X,XXX선 등) 언급 시 반드시 제공된 주간 종가·이전 종가 수치만 사용. 일중 가격·추정치 언급 절대 금지.
1-3. 시가총액 TOP10 종목의 상승·하락 이유는 뉴스 근거 없이 절대 서술하지 말 것 — 종목명과 등락률 수치만 표기. (이 규칙 문구 자체를 본문에 출력하지 말 것)
2. 마크다운 형식, 2000~2800자
3. 단락은 2~3문장 이내로 짧게
4. 어조: 전문적이고 정중한 톤 (~입니다, ~로 분석됩니다)
5. 상승 수치는 빨간색, 하락은 파란색 인라인 스타일 적용:
   - 상승: <span style="color:#e74c3c"><b>+X.XX%</b></span>
   - 하락: <span style="color:#3182f6"><b>-X.XX%</b></span>
6. 종목 표기: **종목명(티커)** 순서로 표기 (예: **삼성전자(005930)**)
7. 이모티콘 규칙: 급등락 항목 문두에 상승 📈, 하락 📉 반드시 삽입
8. {{날짜}}, {{요일}} 등 중괄호 플레이스홀더 절대 출력 금지
9. 문체 규칙 (기계적 반복 금지):
   - '~로 분석됩니다', '~로 판단됩니다', '~로 보입니다'는 각각 글 전체에서 1회 이하.
   - 같은 종결어미 3문장 연속 금지 — 단, 변주는 반드시 존댓말 범위 안에서만
     (~했습니다/~입니다/~습니다 섞기, 반말체 절대 금지). 한 문단 안에 짧은 문장을 1개 이상 섞을 것.
   - 이모지는 지정된 소제목·리스트 외 본문 문장에 추가 금지.
   - '한편', '또한'으로 시작하는 문단은 2개 이하.

구조 (반드시 이 순서로, 제시된 섹션만 작성):
0) 📌 **이번 주 핵심 요약** — 아래 4가지를 3~4문장(이모티콘 제외 200~280자)으로 작성:
   - 문장 1: KOSPI·KOSDAQ 주간 등락률 수치 + 한 줄 평가 (예: 2주 연속 하락 / 반등 성공)
   - 문장 2: 이번 주 가장 큰 하락·상승 원인 (WHY — 외국인 매도, 금리 우려, 섹터 수급 등)
   - 문장 3: 주도 섹터·수급 흐름 핵심 (예: 반도체 강세, 기관 저가 매수 등)
   - 문장 4: 다음 주 관전 포인트 한 줄 예고 — 이번 주 데이터에서 도출되는 추세만
     (예: "반도체 수급 개선 지속 여부가 관건"). 데이터에 없는 구체적 일정(FOMC 등)
     날짜를 추측해 넣지 말 것.

a) ### 📊 주간 시장 지표 ({date_range})
   - 마크다운 테이블: 지수명 | 주간 종가 | 이전 종가 | 주간 등락률 | 주간 흐름 한 줄
   - 등락률 셀에 상승/하락 색상 인라인 스타일 적용
   - 표 아래 단락 1~2개: KOSPI/KOSDAQ 흐름 차이 및 원인 서술
{investor_prompt_sec}
{stocks_prompt_sec}
d) ### 🏭 주간 주도·약세 섹터
   - 마크다운 테이블: 구분 | 섹터명 | 등락률 | 대표 이슈
   - 표 아래 단락 1개: 섹터 흐름 해석

e) ### 📰 이번 주 핵심 뉴스 & 이슈
   - 제공된 뉴스 헤드라인 번호 목록(1. 2. 3.) 3~5개 요약
   - 뉴스 없으면 이번 주 국내 시장 이슈 3개 (AI 지식 기반)

f) ### 🔮 다음 주 전망 ({next_week})
   - ⚠️ 데이터 블록에 없는 구체적 날짜·일정(경제지표 발표일, FOMC 회의일, 기업 실적
     발표일 등)을 AI 지식으로 추측해 서술하는 것 절대 금지. 데이터 블록에는 이런
     일정 정보가 전혀 없음 — 실제 발생한 사고: 이미 지난 FOMC 의사록을 다음 주
     일정으로 안내, CPI 발표일을 실제와 다른 날짜로 기재(3주 연속 발생).
   - 이번 주 데이터(지수·수급·섹터 흐름)에서 직접 도출되는 추세만 2~3문장으로
     전망할 것. "다음 주에도 ~ 흐름이 이어질지 주목됩니다"처럼 날짜·시각이 없는
     일반적 표현만 사용.
   - 특정 날짜·시각이 붙는 일정·이벤트명 언급 자체를 하지 말 것.

출력 형식 — 아래 헤더 뒤에 마크다운 본문만 작성 (면책 조항 포함 금지, 시스템이 자동 추가):
LABELS: {all_labels}
CONTENT:
[마크다운 본문]"""


def _parse_response(raw: str, ref_date: str = "") -> dict:
    labels        = []
    content_lines = []
    in_content    = False
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
        # AI가 CONTENT: 마커를 누락한 경우 — LABELS: 다음 줄부터 전체를 본문으로 처리
        # (마커 부재로 본문이 통째로 빈 문자열이 되는 사고 방지)
        start = labels_line_idx + 1 if labels_line_idx is not None else 0
        content_lines = lines[start:]
        print("  [파싱 경고] CONTENT: 마커 누락 — LABELS: 다음 줄부터 전체를 본문으로 대체 처리")

    md_body = "\n".join(content_lines).strip()
    if ref_date:
        md_body = fix_weekday_labels(md_body, ref_date)

    content = apply_color_spans(md_to_html(md_body)) + "\n" + DISCLAIMER + "\n" + KR_REPORT_LINKS_HTML
    return {"labels": labels, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-sonnet-4-6") -> dict:
    prompt  = build_prompt(data)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw    = message.content[0].text
    result = _parse_response(raw, data.get("week_end", ""))
    result["labels"] = _build_labels(data)  # AI의 LABELS: 출력 대신 Python 고정 라벨로 덮어쓰기
    print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")
    return result
