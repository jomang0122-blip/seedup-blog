# -*- coding: utf-8 -*-
from anthropic import Anthropic
from shared.utils import DISCLAIMER, md_to_html, apply_color_spans

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
        sign = "▲" if v["change_pct"] >= 0 else "▼"
        vol_str = _fmt_vol(v["volume"]) if v["volume"] else "-"
        lines.append(
            f"{v['name']}: {v['close']:,.2f}  {sign}{abs(v['change_pct']):.2f}%  거래량 {vol_str}"
        )
    return "\n".join(lines) if lines else "(지수 데이터 없음)"


def _build_stocks_block(fixed_stocks: dict) -> str:
    lines = []
    for ticker, v in fixed_stocks.items():
        sign = "+" if v["change_pct"] >= 0 else ""
        lines.append(f"{ticker} {v['name']}: ${v['close']:,.2f}  ({sign}{v['change_pct']:.2f}%)")
    return "\n".join(lines) if lines else "(종목 데이터 없음)"


def _build_movers_block(top_movers: list, news: list = None) -> str:
    if not top_movers:
        return "(급등락 종목 없음)"
    if news is None:
        news = []
    parts = []
    news_movers = []
    for m in top_movers:
        icon = "📈" if m["direction"] == "up" else "📉"
        parts.append(f"{icon} {m['ticker']}: {m['change_pct']:+.2f}%")
        matched = next((n for n in news if m["ticker"] in n), "")
        if matched:
            news_movers.append(f"{icon} {m['ticker']}: {m['change_pct']:+.2f}% [뉴스: {matched}]")
    result = "급등락 종목 (티커+등락률만 — 이유 작성 절대 금지):\n" + "\n".join(parts)
    if news_movers:
        result += "\n뉴스기반 급등락 (이 목록만 이유 작성 가능):\n" + "\n".join(news_movers)
    else:
        result += "\n뉴스기반 급등락: (없음 — 이유 섹션 전체 생략)"
    return result


def _build_economic_block(economic_calendar: list) -> str:
    if not economic_calendar:
        return "(경제 지표 없음 — 📋 경제 지표 섹션 전체 생략)"
    lines = []
    for e in economic_calendar:
        actual = e.get("actual")
        estimate = e.get("estimate")
        unit = e.get("unit", "")
        actual_str = f"{actual}{unit}" if actual is not None else "미발표"
        est_str = f"{estimate}{unit}" if estimate is not None else "-"
        lines.append(f"- {e['event']}: 실제 {actual_str} (예상 {est_str})")
    return "\n".join(lines)


def _build_news_block(news: list) -> str:
    if not news:
        return "(뉴스 없음 — 내일 일정만 작성)"
    return "\n".join(f"{i+1}. {h}" for i, h in enumerate(news[:5]))


def _date_kor(us_date: str) -> str:
    try:
        from datetime import datetime as _dt
        d = _dt.strptime(us_date, "%Y-%m-%d")
        return f"{str(d.year)[2:]}년 {d.month}월 {d.day}일"
    except Exception:
        return us_date


def _tomorrow_kst() -> str:
    import pytz
    from datetime import datetime, timedelta
    kst = pytz.timezone("Asia/Seoul")
    tomorrow = datetime.now(kst) + timedelta(days=1)
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    return f"{tomorrow.month}월 {tomorrow.day}일({weekdays[tomorrow.weekday()]})"


def build_prompt(data: dict) -> str:
    us_date      = data.get("us_date", "")
    us_date_kor  = _date_kor(us_date)
    tomorrow_str = _tomorrow_kst()

    news_list     = data.get("news", [])
    indices_block = _build_indices_block(data.get("indices", {}))
    stocks_block  = _build_stocks_block(data.get("fixed_stocks", {}))
    movers_block  = _build_movers_block(data.get("top_movers", []), news_list)
    news_block    = _build_news_block(news_list)
    economic_block = _build_economic_block(data.get("economic_calendar", []))

    has_movers   = bool(data.get("top_movers"))
    has_news     = bool(news_list)
    has_economic = bool(data.get("economic_calendar"))

    movers_skip_note = (
        "\n⚠️ 급등락 종목 데이터 없음 → #### 💥 오늘의 급등락 종목 한눈에 보기 소제목 포함 해당 하위섹션 전체 삭제. 텍스트 한 줄도 출력 금지."
        if not has_movers else ""
    )
    news_skip_note = (
        "\n⚠️ 뉴스 데이터 없음 → ### 📰 오늘의 핵심 뉴스 소제목 포함 해당 섹션 전체 삭제. 텍스트 한 줄도 출력 금지."
        if not has_news else ""
    )
    economic_skip_note = (
        "\n⚠️ 구조화된 경제 지표 데이터 없음 → 뉴스 헤드라인에서 경제 지표 언급(고용·물가·PMI·소비자신뢰 등)이 있으면 해당 내용으로 ### 📋 섹션 작성. 뉴스에도 없으면 섹션 전체 생략."
        if not has_economic else ""
    )

    base_labels   = ["미국증시", "데일리", "시황", "미국주식", "나스닥", "S&P500", "뉴욕증시"]
    mover_labels  = [m["ticker"] for m in data.get("top_movers", [])[:2]]
    all_labels    = ",".join(base_labels + mover_labels)

    return f"""당신은 대한민국 최고의 미국 주식 시황 분석가이자 SEO 전문가입니다.
SeedUP INVEST 블로그에 올릴 미국 증시 데일리 시황 포스팅을 한국어로 작성하세요.
블로그 설명: "매일 아침 미국 증시 마감 시황을 정리해 드립니다. 출근 전 1분으로 핵심만 확인하세요."

━━━ 미국 시장 데이터 ({us_date} 마감 기준) ━━━

[3대 지수]
{indices_block}

[한국인 관심 종목]
{stocks_block}

[오늘의 급등락 TOP 3]{movers_skip_note}
{movers_block}

[당일 발표 경제 지표]{economic_skip_note}
{economic_block}

[뉴스 헤드라인 (영어 → 한국어로 요약)]{news_skip_note}
{news_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[작성 지침]
1. 위 데이터의 수치를 한 글자도 바꾸지 말 것 (환각 절대 금지)
2. 마크다운 형식, 2000~2800자
3. 스마트폰 가독성: 단락은 2~3문장 이내로 짧게
4. 어조: 전문적이고 정중한 톤 (~입니다, ~로 분석됩니다)
5. 상승 수치는 빨간색(style="color:#e74c3c"), 하락은 파란색(style="color:#3182f6") 인라인 스타일 적용
6. {{금요일}}, {{날짜}}, {{시각}} 등 중괄호 플레이스홀더 절대 출력 금지 — 반드시 실제 날짜/요일로 대체할 것
7. 종목 표기 포맷: 반드시 **티커(한글종목명)** 순서로 표기. 영문명 단독 표기 금지.
   - 한글명은 위 [한국인 관심 종목] 데이터 블록에 있는 이름을 그대로 사용. 임의 변경·번역 금지.
8. 이모티콘 규칙: 급등락 리스트 각 항목 문두에 상승 종목 📈, 하락 종목 📉 반드시 삽입

구조 (반드시 이 순서로):
0) 📌 **오늘 미국증시 핵심** (구글 검색 설명으로 노출됨 — 날짜·나스닥·S&P500·다우 등락률·핵심 종목 키워드를 첫 2문장 안에 반드시 포함. 이모티콘 제외 150자 이내로 압축)

a) ### 📊 3대 지수 ({us_date_kor} 마감)
   - 마크다운 테이블: 지수명 | 종가 | 등락률 | 거래량
   - 등락률 셀에 상승/하락 색상 인라인 스타일 적용

b) ### 🔥 오늘의 주목 종목
   - 마크다운 테이블: 종목 | 종가 | 등락률 | 한줄 동향
     * 종목 컬럼: 반드시 **TICKER(한글명)** 형식으로 표기 (예: **NVDA(엔비디아)**)
     * 한줄 동향: 4~10자 한국어 (예: 차익실현, AI 수혜 기대, 실적 호조, 보합)
   - 표 아래 단락 2~3개: 수치 반복 나열 절대 금지. 대형 기술주 간 수급 인과관계를 담백하게 서술
   - #### 💥 오늘의 급등락 종목 한눈에 보기
   - 데이터 블록 '급등락 종목' 목록을 아래 형식으로 출력 (이유 작성 절대 금지):
     📈 TICKER(한글명) +X.X%
     📉 TICKER(한글명) -X.X%
   - 데이터 블록 '뉴스기반 급등락' 목록이 있을 때만 아래 형식으로 이유 추가:
     📰 TICKER(한글명) +X.X% — [해당 종목 [뉴스] 내용에서만 추출한 이유]
   - '뉴스기반 급등락: (없음)'이면 이유 섹션 전체 생략

c) ### 📋 오늘의 경제 지표
   - 데이터 블록 '당일 발표 경제 지표' 내용을 한국어로 정리
   - 각 지표: 지표명 / 실제 vs 예상 비교 / 시장 영향 한 줄
   - 데이터 없음이면 이 섹션 전체 생략

d) ### 📰 오늘의 핵심 뉴스
   - 제공된 뉴스 헤드라인을 한국어로 요약 번호 목록(1. 2. 3.) 3개
   - 뉴스 없으면 시장 전반 흐름 요약 3개

e) ### 📅 내일 주목할 일정 ({tomorrow_str})
   - 미국 경제 지표 발표, 실적 발표 등 1~2개 (AI 지식 기반)
   - 날짜+요일+KST 시각 명시 (예: {tomorrow_str} 오후 9시 30분)
   - 플레이스홀더 절대 금지 — 날짜/요일을 모르면 생략하고 종목/지표명만 작성

출력 형식 — 아래 헤더 뒤에 마크다운 본문만 작성 (면책 조항은 포함하지 말 것. 시스템이 자동 추가):
LABELS: {all_labels}
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

    content = apply_color_spans(md_to_html("\n".join(content_lines).strip())) + "\n" + DISCLAIMER
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
