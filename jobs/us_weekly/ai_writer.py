# -*- coding: utf-8 -*-
from anthropic import Anthropic
from shared.utils import DISCLAIMER, US_REPORT_LINKS_HTML, md_to_html, apply_color_spans, fix_weekday_labels

client = Anthropic()


def _fmt_vol(vol: int) -> str:
    if vol >= 1_000_000_000:
        return f"{vol / 1_000_000_000:.1f}B"
    if vol >= 1_000_000:
        return f"{vol / 1_000_000:.0f}M"
    return str(vol)


def _build_indices_block(indices: dict) -> str:
    lines = []
    for ticker, v in indices.items():
        sign = "▲" if (v["weekly_pct"] or 0) >= 0 else "▼"
        vol_str = _fmt_vol(v["volume"]) if v["volume"] else "-"
        lines.append(
            f"{v['name']}: {v['close']:,.2f}  {sign}{abs(v['weekly_pct'] or 0):.2f}%  거래량 {vol_str}"
        )
    return "\n".join(lines) if lines else "(지수 데이터 없음)"


def _build_stocks_block(fixed_stocks: dict) -> str:
    lines = []
    for ticker, v in fixed_stocks.items():
        close = v.get("close")
        pct = v.get("weekly_pct")
        if close is not None and pct is not None:
            sign = "+" if pct >= 0 else ""
            price_str = f"${close:,.2f}  ({sign}{pct:.2f}%)"
        else:
            price_str = "N/A (데이터 없음)"
        lines.append(f"{ticker} {v['name']}: {price_str}")
    return "\n".join(lines) if lines else "(종목 데이터 없음)"


def _build_movers_block(top_movers: list) -> str:
    """급등락 종목별 실제 개별 뉴스(data_collector._mover_news 결과)만 이유 근거로 사용.
    뉴스 매칭 로직이 아예 없어 AI가 근거 없이 이유를 지어내던 문제 수정."""
    if not top_movers:
        return "(급등락 종목 없음)"
    lines = []
    news_movers = []
    for m in top_movers:
        icon = "📈" if m["direction"] == "up" else "📉"
        label = f"{m['ticker']}({m.get('name', m['ticker'])})"
        close_str = f"${m['close']:,.2f}" if m.get("close") is not None else "-"
        lines.append(f"{icon} {label}: {close_str}  {m['weekly_pct']:+.2f}%")
        matched = m.get("news", "")
        if matched:
            news_movers.append(f"{icon} {label}: {m['weekly_pct']:+.2f}% [뉴스: {matched}]")
    result = "\n".join(lines)
    if news_movers:
        result += "\n뉴스기반 급등락 (이 목록에 있는 종목만 이유 작성 가능):\n" + "\n".join(news_movers)
    else:
        result += "\n뉴스기반 급등락: (없음 — 이유 칸은 모두 '-'로 표기)"
    return result


def _build_news_block(news: list) -> str:
    if not news:
        return "(뉴스 없음)"
    return "\n".join(f"{i+1}. {h}" for i, h in enumerate(news[:5]))


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

    week_end가 항상 금요일이라고 가정하고 +3일/+7일로 계산했었는데,
    data_collector가 ISO 주차의 "실제 마지막 거래일"을 쓰도록 바뀌면서
    금요일이 휴장(대체휴일 등)인 주엔 week_end가 목요일 등이 될 수 있음.
    그 경우 +3일 계산이 일요일이 되는 등 틀어져서 "다음 주"에 이미 지난
    날짜(예: 이미 지난 독립기념일)가 끼어드는 사고가 발생했다(2026-07-05 실측).
    요일에 무관하게 "week_end 다음의 첫 월요일"을 직접 찾도록 수정.
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
    base_labels  = ["미국증시", "위클리", "주간시황", "미국주식", "나스닥", "S&P500", "뉴욕증시", "미국위클리"]
    mover_labels = [m["ticker"] for m in data.get("top_movers", [])[:2]]
    return base_labels + mover_labels


def _build_retry_feedback(prev_issues: list = None) -> str:
    """직전 시도의 검증 실패 사유를 다음 생성 프롬프트에 피드백 — 동일 프롬프트로
    재시도해 같은 유형의 창작이 반복되는 문제 방지(2026-07-13 kr_daily에서 확인된
    패턴, us_weekly에도 동일 적용)."""
    if not prev_issues:
        return ""
    lines = [f"- [{i.get('type', '')}] {i.get('description', '')}" for i in prev_issues]
    return (
        "\n\n⚠️ 직전 시도에서 아래 문제로 반려됨 — 동일 실수 반복 금지, "
        "특히 데이터에 없는 구체적 사건·수치를 창작하지 말 것:\n"
        + "\n".join(lines)
    )


def build_prompt(data: dict, prev_issues: list = None) -> str:
    week_start = data.get("week_start", "")
    week_end   = data.get("week_end", "")
    date_range = _date_range_kor(week_start, week_end)
    next_week  = _next_week_str(week_end)

    indices_block = _build_indices_block(data.get("indices", {}))
    stocks_block  = _build_stocks_block(data.get("fixed_stocks", {}))
    movers_block  = _build_movers_block(data.get("top_movers", []))
    news_block    = _build_news_block(data.get("news", []))

    has_movers = bool(data.get("top_movers"))
    has_news   = bool(data.get("news"))

    movers_skip_note = (
        "\n⚠️ 급등락 종목 데이터 없음 → #### 💥 주간 급등락 TOP3 소제목 포함 해당 하위섹션 전체 삭제. 텍스트 한 줄도 출력 금지."
        if not has_movers else ""
    )
    news_skip_note = (
        "\n⚠️ 뉴스 데이터 없음 → ### 📰 이번 주 핵심 뉴스 & 이슈 소제목 포함 해당 섹션 전체 삭제. 텍스트 한 줄도 출력 금지."
        if not has_news else ""
    )

    all_labels   = ",".join(_build_labels(data))

    return f"""당신은 대한민국 최고의 미국 주식 시황 분석가이자 SEO 전문가입니다.
SeedUP INVEST 블로그에 올릴 미국 증시 주간 시황 포스팅을 한국어로 마크다운 형식으로 작성하세요.
블로그 설명(참고용 — 본문에 이 문장을 그대로 베끼거나 결말 인사말로 반복 출력 금지): "매주 미국 증시 주간 흐름을 정리해 드립니다. 이번 주 핵심과 다음 주 전망을 한눈에 확인하세요."

━━━ 미국 시장 주간 데이터 ({week_start} ~ {week_end}) ━━━

[3대 지수 주간 등락률]
{indices_block}

[한국인 관심 종목 주간 성적]
{stocks_block}

[주간 급등락 TOP 3 (워치리스트 기준)]{movers_skip_note}
{movers_block}

[주간 뉴스 헤드라인 (영어 → 한국어로 요약)]{news_skip_note}
{news_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[작성 지침]
1. 위 데이터의 수치를 한 글자도 바꾸지 말 것 (환각 절대 금지)
2. 마크다운 형식, 2000~2800자
3. 단락은 2~3문장 이내로 짧게
4. 어조: 전문적이고 정중한 톤 (~입니다, ~로 분석됩니다)
5. 상승 수치는 빨간색, 하락은 파란색 인라인 스타일 적용:
   - 상승: <span style="color:#e74c3c"><b>+X.XX%</b></span>
   - 하락: <span style="color:#3182f6"><b>-X.XX%</b></span>
6. 종목 표기 포맷: 반드시 **티커(한글종목명)** 순서로 표기. 영문명 단독 표기 금지.
   - 한글명은 위 데이터 블록에 있는 이름을 그대로 사용. 임의 변경 금지.
7. 이모티콘 규칙: 급등락 항목 문두에 상승 📈, 하락 📉 반드시 삽입
8. {{날짜}}, {{요일}} 등 중괄호 플레이스홀더 절대 출력 금지
9. 문체 규칙 (기계적 반복 금지):
   - '~로 분석됩니다', '~로 판단됩니다', '~로 보입니다'는 각각 글 전체에서 1회 이하.
   - 같은 종결어미 3문장 연속 금지 — 단, 변주는 반드시 존댓말 범위 안에서만
     (~했습니다/~입니다/~습니다 섞기, 반말체 절대 금지). 한 문단 안에 짧은 문장을 1개 이상 섞을 것.
   - 이모지는 지정된 소제목·리스트 외 본문 문장에 추가 금지.
   - '한편', '또한'으로 시작하는 문단은 2개 이하.

구조 (반드시 이 순서로):
0) 📌 **이번 주 미국증시 핵심** (구글 검색 설명으로 노출됨 — 주간 나스닥·S&P500·다우 등락률·핵심 이슈를 첫 2문장 안에 반드시 포함. 이모티콘 제외 150자 이내로 압축)

a) ### 📊 주간 3대 지수 성적 ({date_range})
   - 마크다운 테이블: 지수명 | 주간 종가 | 주간 등락률 | 주간 흐름 한 줄
   - 등락률 셀에 상승/하락 색상 인라인 스타일 적용
   - 표 아래 단락 1~2개: 3대 지수 간 흐름 차이 및 원인 서술

b) ### 🔥 한국인 관심 종목 주간 성적
   - 마크다운 테이블: 종목 | 주간 종가 | 주간 등락률 | 한줄 동향
     * ⚠️ [한국인 관심 종목] 데이터 블록의 모든 종목을 한 종목도 빠짐없이 테이블에 포함할 것 (임의 삭제 절대 금지)
     * "N/A (데이터 없음)" 종목도 행 유지 — 종가·등락률 칸에 "확인 불가" 표기
     * 종목 컬럼: 반드시 **TICKER(한글명)** 형식 (예: **NVDA(엔비디아)**)
     * 한줄 동향: 4~10자 한국어
   - 표 아래 단락 1~2개: 주요 종목 간 수급 흐름 서술
   - #### 💥 주간 급등락 TOP3
     마크다운 테이블: 종목 | 주간 종가 | 주간 등락률 | 핵심 이유
     * 종목 컬럼: 📈/📉 이모티콘 + **TICKER(한글명)** 형식 (예: 📈 **MSTR(스트래티지)**) — 한글명은 데이터 블록 표기 그대로, 창작 금지
     * 주간 종가·등락률은 위 [주간 급등락 TOP 3] 데이터 블록 수치 그대로 사용
     * 핵심 이유 칸: 데이터 블록 '뉴스기반 급등락' 목록에 있는 종목만 그 [뉴스] 내용에서 이유 작성 가능. 목록에 없는 종목은 이유 칸에 "-"만 표기 — 임의 이유 생성 절대 금지

c) ### 📰 이번 주 핵심 뉴스 & 이슈
   - 제공된 뉴스 헤드라인 한국어 요약 번호 목록(1. 2. 3.) 3~5개
   - 뉴스 없으면 이번 주 시장 전반 흐름 이슈 3개 (AI 지식 기반)

d) ### 🔮 다음 주 전망 ({next_week})
   - ⚠️ 데이터 블록에 없는 구체적 날짜·일정(FOMC 회의일, 경제지표 발표일, 실적
     발표일 등)을 AI 지식으로 추측해 서술하는 것 절대 금지. 데이터 블록에는 이런
     일정 정보가 전혀 없음 — 실제 발생한 사고: 이미 지난 FOMC 의사록을 다음 주
     일정으로 안내, CPI 발표일을 실제와 다른 날짜로 기재(3주 연속 발생).
   - 이번 주 데이터(지수·수급·급등락 종목)에서 직접 도출되는 추세만 2~3문장으로
     전망할 것. 날짜·시각이 붙는 구체적 일정·이벤트명 언급 자체를 하지 말 것.

출력 형식 — 아래 헤더 뒤에 마크다운 본문만 작성 (면책 조항은 포함하지 말 것. 시스템이 자동 추가):
LABELS: {all_labels}
CONTENT:
[마크다운 본문]""" + _build_retry_feedback(prev_issues)


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
        # AI가 CONTENT: 마커를 누락한 경우 — LABELS: 다음 줄부터 전체를 본문으로 처리
        start = labels_line_idx + 1 if labels_line_idx is not None else 0
        content_lines = lines[start:]
        print("  [파싱 경고] CONTENT: 마커 누락 — LABELS: 다음 줄부터 전체를 본문으로 대체 처리")

    md_body = "\n".join(content_lines).strip()
    if ref_date:
        md_body = fix_weekday_labels(md_body, ref_date)

    content = apply_color_spans(md_to_html(md_body)) + "\n" + DISCLAIMER + "\n" + US_REPORT_LINKS_HTML
    return {"labels": labels, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-sonnet-4-6", prev_issues: list = None) -> dict:
    prompt = build_prompt(data, prev_issues=prev_issues)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text
    result = _parse_response(raw, data.get("week_end", ""))
    result["labels"] = _build_labels(data)  # AI의 LABELS: 출력 대신 Python 고정 라벨로 덮어쓰기
    print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")
    return result
