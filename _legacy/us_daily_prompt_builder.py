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


def _build_movers_block(top_movers: list) -> str:
    if not top_movers:
        return "(급등락 종목 없음)"
    lines = []
    for m in top_movers:
        icon = "📈" if m["direction"] == "up" else "📉"
        lines.append(f"{icon} {m['ticker']}: {m['change_pct']:+.2f}%")
    return "\n".join(lines)


def _build_news_block(news: list) -> str:
    if not news:
        return "(뉴스 없음 — 내일 일정만 작성)"
    return "\n".join(f"{i+1}. {h}" for i, h in enumerate(news[:5]))


def _date_kor(us_date: str) -> str:
    """'2026-06-28' → '26년 6월 28일'"""
    try:
        from datetime import datetime as _dt
        d = _dt.strptime(us_date, "%Y-%m-%d")
        return f"{str(d.year)[2:]}년 {d.month}월 {d.day}일"
    except Exception:
        return us_date


def _tomorrow_kst() -> str:
    """내일 KST 날짜+요일 문자열 반환. 예: '6월 30일(월)'"""
    import pytz
    from datetime import datetime, timedelta
    kst = pytz.timezone("Asia/Seoul")
    tomorrow = datetime.now(kst) + timedelta(days=1)
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    return f"{tomorrow.month}월 {tomorrow.day}일({weekdays[tomorrow.weekday()]})"


def build_prompt(data: dict) -> str:
    us_date = data.get("us_date", "")
    us_date_kor = _date_kor(us_date)
    tomorrow_str = _tomorrow_kst()

    indices_block = _build_indices_block(data.get("indices", {}))
    stocks_block = _build_stocks_block(data.get("fixed_stocks", {}))
    movers_block = _build_movers_block(data.get("top_movers", []))
    news_block = _build_news_block(data.get("news", []))

    return f"""당신은 대한민국 최고의 미국 주식 시황 분석가이자 SEO 전문가입니다.
SeedUP INVEST 블로그에 올릴 미국 증시 데일리 시황 포스팅을 한국어로 작성하세요.
블로그 설명: "매일 아침 미국 증시 마감 시황을 정리해 드립니다. 출근 전 1분으로 핵심만 확인하세요."

━━━ 미국 시장 데이터 ({us_date} 마감 기준) ━━━

[3대 지수]
{indices_block}

[한국인 관심 종목]
{stocks_block}

[오늘의 급등락 TOP 3 (워치리스트 기준)]
{movers_block}

[뉴스 헤드라인 (영어 → 한국어로 요약)]
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
a) ### 📊 3대 지수 ({us_date_kor} 마감)
   - 마크다운 테이블: 지수명 | 종가 | 등락률 | 거래량
   - 등락률 셀에 상승/하락 색상 인라인 스타일 적용

b) ### 🔥 오늘의 주목 종목
   - 마크다운 테이블: 종목 | 종가 | 등락률 | 한줄 동향
     * 종목 컬럼: 반드시 **TICKER(한글명)** 형식으로 표기 (예: **NVDA(엔비디아)**)
     * 한줄 동향: 4~10자 한국어 (예: 차익실현, AI 수혜 기대, 실적 호조, 보합)
     * 뉴스에서 이유 파악 가능하면 뉴스 기반으로, 없으면 수치 기반으로 작성
   - 표 아래 단락 2~3개: 수치 반복 나열 절대 금지. 대형 기술주 간 수급 인과관계를 담백하게 서술
     (예: "NVDA의 실적 서프라이즈가 AI 반도체 섹터 전반을 견인했습니다. 반면 MSFT는 Azure 성장률 우려로 차익실현 매물이 출회되었습니다.")
   - #### 💥 오늘의 급등락 종목 한눈에 보기
   - 당일 유의미한 거래량과 함께 급등락이 나온 종목을 아래 형식으로 출력:
     📈 TICKER(한글명) +X.X% — 핵심 상승 이유 한 줄
     📉 TICKER(한글명) -X.X% — 핵심 하락 이유 한 줄
   - 상승 종목은 반드시 📈, 하락 종목은 반드시 📉 이모티콘을 문두에 삽입

c) ### 📰 오늘의 핵심 뉴스
   - 제공된 뉴스 헤드라인을 한국어로 요약 번호 목록(1. 2. 3.) 3개
   - 뉴스 없으면 시장 전반 흐름 요약 3개

d) ### 📅 내일 주목할 일정 ({tomorrow_str})
   - 미국 경제 지표 발표, 실적 발표 등 1~2개 (AI 지식 기반)
   - 날짜+요일+KST 시각 명시 (예: {tomorrow_str} 오후 9시 30분)
   - 플레이스홀더 절대 금지 — 날짜/요일을 모르면 생략하고 종목/지표명만 작성

출력 형식 — 아래 헤더 뒤에 마크다운 본문만 작성 (면책 조항은 포함하지 말 것. 시스템이 자동 추가):
LABELS: 미국증시,데일리,시황,미국주식,나스닥,S&P500,뉴욕증시
CONTENT:
[마크다운 본문]"""



def _parse_response(raw: str) -> dict:
    labels = []
    content_lines = []
    in_content = False

    for line in raw.split("\n"):
        if line.startswith("LABELS:"):
            raw_labels = line.removeprefix("LABELS:").strip()
            labels = [l.strip() for l in raw_labels.split(",") if l.strip()]
        elif line.startswith("CONTENT:"):
            in_content = True
        elif in_content:
            content_lines.append(line)

    content = md_to_html("\n".join(content_lines).strip()) + "\n" + DISCLAIMER
    return {"labels": labels, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-haiku-4-5-20251001") -> dict:
    """수집 데이터 → Claude → {labels, content, char_count}"""
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
