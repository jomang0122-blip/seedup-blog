# -*- coding: utf-8 -*-
from anthropic import Anthropic
from shared.utils import DISCLAIMER, md_to_html

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
        sign = "+" if (v["weekly_pct"] or 0) >= 0 else ""
        lines.append(f"{ticker} {v['name']}: ${v['close']:,.2f}  ({sign}{v['weekly_pct']:.2f}%)")
    return "\n".join(lines) if lines else "(종목 데이터 없음)"


def _build_movers_block(top_movers: list) -> str:
    if not top_movers:
        return "(급등락 종목 없음)"
    lines = []
    for m in top_movers:
        icon = "📈" if m["direction"] == "up" else "📉"
        lines.append(f"{icon} {m['ticker']}: {m['weekly_pct']:+.2f}%")
    return "\n".join(lines)


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
    """다음 주 월~금 날짜 범위 문자열."""
    try:
        from datetime import datetime as _dt
        end = _dt.strptime(week_end, "%Y-%m-%d")
        next_mon = end + __import__("datetime").timedelta(days=3)
        next_fri = end + __import__("datetime").timedelta(days=7)
        return f"{next_mon.month}월 {next_mon.day}일~{next_fri.day}일"
    except Exception:
        return "다음 주"


def build_prompt(data: dict) -> str:
    week_start = data.get("week_start", "")
    week_end   = data.get("week_end", "")
    date_range = _date_range_kor(week_start, week_end)
    next_week  = _next_week_str(week_end)

    indices_block = _build_indices_block(data.get("indices", {}))
    stocks_block  = _build_stocks_block(data.get("fixed_stocks", {}))
    movers_block  = _build_movers_block(data.get("top_movers", []))
    news_block    = _build_news_block(data.get("news", []))

    return f"""당신은 대한민국 최고의 미국 주식 시황 분석가이자 SEO 전문가입니다.
SeedUP INVEST 블로그에 올릴 미국 증시 주간 시황 포스팅을 한국어로 마크다운 형식으로 작성하세요.
블로그 설명: "매주 미국 증시 주간 흐름을 정리해 드립니다. 이번 주 핵심과 다음 주 일정을 한눈에 확인하세요."

━━━ 미국 시장 주간 데이터 ({week_start} ~ {week_end}) ━━━

[3대 지수 주간 등락률]
{indices_block}

[한국인 관심 종목 주간 성적]
{stocks_block}

[주간 급등락 TOP 3 (워치리스트 기준)]
{movers_block}

[주간 뉴스 헤드라인 (영어 → 한국어로 요약)]
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

구조 (반드시 이 순서로):
a) ### 📊 주간 3대 지수 성적 ({date_range})
   - 마크다운 테이블: 지수명 | 주간 종가 | 주간 등락률 | 주간 흐름 한 줄
   - 등락률 셀에 상승/하락 색상 인라인 스타일 적용
   - 표 아래 단락 1~2개: 3대 지수 간 흐름 차이 및 원인 서술

b) ### 🔥 한국인 관심 종목 주간 성적
   - 마크다운 테이블: 종목 | 주간 종가 | 주간 등락률 | 한줄 동향
     * 종목 컬럼: 반드시 **TICKER(한글명)** 형식 (예: **NVDA(엔비디아)**)
     * 한줄 동향: 4~10자 한국어
   - 표 아래 단락 1~2개: 주요 종목 간 수급 흐름 서술
   - #### 💥 주간 급등락 TOP3
     📈/📉 TICKER(한글명) +X.X% — 핵심 이유 한 줄

c) ### 📰 이번 주 핵심 뉴스 & 이슈
   - 제공된 뉴스 헤드라인 한국어 요약 번호 목록(1. 2. 3.) 3~5개
   - 뉴스 없으면 이번 주 시장 전반 흐름 이슈 3개

d) ### 🔮 다음 주 주목 일정 ({next_week})
   - FOMC, 경제지표, 주요 실적 발표 등 1~3개 (AI 지식 기반)
   - 날짜+KST 시각 명시
   - 플레이스홀더 금지 — 날짜/일정을 모르면 지표명만 작성

출력 형식 — 아래 헤더 뒤에 마크다운 본문만 작성 (면책 조항은 포함하지 말 것. 시스템이 자동 추가):
LABELS: 미국증시,위클리,주간시황,미국주식,나스닥,S&P500,뉴욕증시
CONTENT:
[마크다운 본문]"""


def _parse_response(raw: str) -> dict:
    labels = []
    content_lines = []
    in_content = False

    for line in raw.split("\n"):
        if line.startswith("LABELS:"):
            labels = [l.strip() for l in line.removeprefix("LABELS:").strip().split(",") if l.strip()]
        elif line.startswith("CONTENT:"):
            in_content = True
        elif in_content:
            content_lines.append(line)

    content = md_to_html("\n".join(content_lines).strip()) + "\n" + DISCLAIMER
    return {"labels": labels, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-haiku-4-5-20251001") -> dict:
    prompt = build_prompt(data)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text
    result = _parse_response(raw)
    print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")
    return result
