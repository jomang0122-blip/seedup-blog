# -*- coding: utf-8 -*-
import os
from anthropic import Anthropic

client = Anthropic()


# ── 포맷 유틸 ─────────────────────────────────────────────────────────────

def _fmt_won(amount) -> str:
    """None 허용 — 억/조 단위 변환"""
    if amount is None:
        return None
    abs_val = abs(amount)
    if abs_val >= 1_000_000_000_000:
        return f"{amount / 1_000_000_000_000:.1f}조원"
    if abs_val >= 100_000_000:
        return f"{amount / 100_000_000:.0f}억원"
    return f"{amount:,}원"


def _direction(value) -> str:
    if value is None:
        return ""
    return "순매수" if value >= 0 else "순매도"


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────

def _build_prompt(data: dict) -> str:
    date   = data.get("date", "")
    kospi  = data.get("kospi",  {})
    kosdaq = data.get("kosdaq", {})

    kospi_line = ""
    if kospi:
        sign = "▲" if kospi["change_pct"] > 0 else "▼"
        kospi_line = (
            f"KOSPI  {kospi['close']:,.2f}pt  "
            f"{sign}{abs(kospi['change']):.2f}pt ({kospi['change_pct']:+.2f}%)"
        )

    kosdaq_line = ""
    if kosdaq:
        sign = "▲" if kosdaq["change_pct"] > 0 else "▼"
        kosdaq_line = (
            f"KOSDAQ {kosdaq['close']:,.2f}pt  "
            f"{sign}{abs(kosdaq['change']):.2f}pt ({kosdaq['change_pct']:+.2f}%)"
        )

    # 수급
    foreign     = data.get("foreign_net")
    institution = data.get("institution_net")
    investor_section = ""
    if foreign is not None:
        investor_section = (
            f"외국인: {_fmt_won(abs(foreign))} {_direction(foreign)}\n"
            f"기관:   {_fmt_won(abs(institution))} {_direction(institution)}"
        )

    # 섹터
    def sector_lines(sectors):
        return "  " + ", ".join(f"{s['name']}({s['change_pct']:+.2f}%)" for s in sectors) if sectors else "(데이터 없음)"

    top_sec_txt = sector_lines(data.get("top_sectors",    []))
    bot_sec_txt = sector_lines(data.get("bottom_sectors", []))

    # 시장 전체 뉴스
    news = data.get("news", [])
    news_txt = ""
    if news:
        news_txt = "시장 전체 뉴스:\n" + "\n".join(f"  - {n}" for n in news[:5])

    # 종목별 뉴스 — gainers/losers 데이터에 주입
    stock_news = data.get("stock_news", {})

    def stock_lines_with_news(stocks):
        """뉴스가 있는 종목만 포함 — 뉴스 없으면 목록에서 제외"""
        if not stocks:
            return "(데이터 없음)"
        lines = []
        for s in stocks:
            headlines = stock_news.get(s["name"], [])
            if not headlines:
                continue  # 뉴스 없으면 제외
            line = f"  - {s['name']}  {s['change_pct']:+.2f}%"
            line += "\n     관련뉴스: " + " / ".join(headlines[:2])
            lines.append(line)
        return "\n".join(lines) if lines else "(뉴스 수집된 종목 없음)"

    gainers_txt = stock_lines_with_news(data.get("top_gainers", []))
    losers_txt  = stock_lines_with_news(data.get("top_losers",  []))

    # 제목용 날짜 포맷: "2026-06-25" → "26년 6월 25일"
    try:
        from datetime import datetime as _dt
        _d = _dt.strptime(date, "%Y-%m-%d")
        date_title = f"{str(_d.year)[2:]}년 {_d.month}월 {_d.day}일"
    except Exception:
        date_title = date

    # 섹터 데이터 유무 판단
    has_sectors = bool(data.get("top_sectors") or data.get("bottom_sectors"))

    prompt = f"""당신은 한국 주식 시장 전문 블로그 작가입니다.
SeedUP INVEST 블로그(seedup-invest.blogspot.com)에 올릴 오늘({date}) 마감 시황 포스팅을 작성하세요.
블로그 설명: "매일 한국 주식 시황, 당일 주도 섹터 및 특징주 리포트. 시드머니를 키우는 가장 확실한 투자 인사이트, SeedUp INVEST"

━━━ 오늘의 시장 데이터 ━━━
{kospi_line}
{kosdaq_line}
{investor_section if investor_section else "(수급 데이터 미수집)"}

주도 섹터 TOP3: {top_sec_txt}
약세 섹터 TOP3: {bot_sec_txt}

주요 급등주 (뉴스 확인된 종목만):
{gainers_txt}

주요 급락주 (뉴스 확인된 종목만):
{losers_txt}

{news_txt}
━━━━━━━━━━━━━━━━━━━━━━━━━━━

작성 규칙:
1. HTML 형식 (Blogger에 바로 붙여 넣는 포맷)
2. 분량: HTML 태그 포함 2000~2800자
3. 구조 (반드시 이 순서로):
   a) <h2> 제목: 반드시 "[{date_title} 시황] 핵심내용" 형식으로 시작
   b) <h3>🚀 오늘 시장 핵심</h3> — 지수·섹터·특징주를 아우르는 2~3문장 요약
   c) <h3>📊 지수 동향</h3> — KOSPI/KOSDAQ 각각 별도 <p>로 수치 포함 서술
   d) <h3>🏭 주도 섹터</h3> — 상승 섹터와 하락 섹터를 각각 <ul><li>로 나열. 왜 그 섹터가 움직였는지 한 줄 설명 추가{'(섹터 데이터 없음 — 이 섹션 생략)' if not has_sectors else ''}
   e) <h3>🔥 특징주 리포트</h3> — 급등·급락 각각 <ul><li> 리스트로 작성. 반드시 아래 데이터에 있는 종목만 포함. 종목마다 등락률 + 관련뉴스 한 줄 요약. 데이터에 없는 종목은 절대 추가하지 말 것
   f) <h3>💡 시드업 인사이트</h3> — 오늘 시장에서 시드머니를 키우는 투자자 관점의 핵심 관찰 2~3가지. 구체적이고 실용적으로
   g) <h3>🧭 내일 시장 전망</h3> — 신중한 어조로 2~3문장
   h) 면책 문구: h3/h4 제목 없이 아래 문구를 <p> 태그로만 출력 (한 글자도 바꾸지 말 것):
      <p style="margin-top:30px; padding:15px; background:#f5f5f5; border-left:4px solid #999; font-size:12px; color:#666;">⚠️ 본 포스트는 시장 정보 제공 및 교육 목적으로 작성된 것이며, 어떤 식으로든 특정 종목 또는 금융상품의 매매를 추천하는 것이 아닙니다. 투자 결정은 반드시 개인의 투자 목표, 위험 선호도, 재무 상황을 고려하여 신중히 진행하시기 바랍니다. SeedUP 투자 블로그는 본 내용으로 인한 모든 직·간접적 손실에 대해 책임을 지지 않습니다. ⚠️</p>
4. 어투: 전문적이지만 읽기 쉬운 한국어, 딱딱하지 않게. 실질적인 인사이트 위주
5. null/없는 데이터는 자연스럽게 생략 (언급하지 말 것)
6. SEO: '코스피', '오늘 증시', '주식시장', '섹터', '특징주' 키워드를 제목/본문에 자연스럽게 포함

⚠️ 반드시 지켜야 할 4가지 규칙:
A. 숫자 정확성: 제목의 수치는 반드시 실제 데이터와 일치. 급등 1위 종목 수치로 제목 작성. 여러 종목을 묶어 "XX% 이상"으로 쓰면 안 됨 — 각 종목 수치를 정확히 기재.
B. 리스트 형식: 급등/급락 종목·섹터는 반드시 <ul><li> HTML 리스트 사용. 각 항목에 수치 필수 기재.
C. 단락 여백: 모든 <p> 태그는 2~3문장 이내로 짧게. 긴 단락은 반드시 쪼갤 것 (애드센스 광고 삽입 공간 확보).
D. 환각 금지 (가장 중요): 종목 이유는 반드시 위 "관련뉴스" 항목에 있는 내용만 사용할 것.
   - 데이터에 있는 종목만 작성, 없는 종목 추가 금지
   - 관련뉴스 내용만 한 줄 요약, 뉴스 벗어난 이유 창작 금지
   - 예시: <li>SK하이닉스 +13.06% — 마이크론 실적 호조로 반도체 업종 수혜</li>

출력 형식 — 아래 3줄 헤더 뒤에 HTML 본문만 작성 (다른 설명 없음):
TITLE: [{date_title} 시황] 핵심내용 (예: [{date_title} 시황] 코스피 5.42% 폭등! 반도체 섹터 주도)
LABELS: 코스피,코스닥,시황,주식,오늘증시,섹터분석,특징주
CONTENT:
[HTML 본문]"""

    return prompt


# ── 파싱 ─────────────────────────────────────────────────────────────────

def _parse_response(raw: str) -> dict:
    title   = ""
    labels  = []
    content_lines = []
    in_content = False

    for line in raw.split("\n"):
        if line.startswith("TITLE:"):
            title = line.removeprefix("TITLE:").strip()
        elif line.startswith("LABELS:"):
            raw_labels = line.removeprefix("LABELS:").strip()
            labels = [l.strip() for l in raw_labels.split(",") if l.strip()]
        elif line.startswith("CONTENT:"):
            in_content = True
        elif in_content:
            content_lines.append(line)

    content = "\n".join(content_lines).strip()
    return {"title": title, "labels": labels, "content": content,
            "char_count": len(content)}


# ── 공개 API ──────────────────────────────────────────────────────────────

def generate_post(data: dict,
                  model: str = "claude-haiku-4-5-20251001") -> dict:
    """수집 데이터 → Claude → {title, labels, content, char_count}"""
    prompt = _build_prompt(data)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text
    result = _parse_response(raw)

    print(f"  [작성] 제목: {result['title']}")
    print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")
    return result


# ── 단독 테스트 ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 샘플 데이터로 테스트
    sample = {
        "date": "2026-06-25",
        "kospi":  {"close": 8930.30, "change": 459.14, "change_pct": 5.42, "volume": 449320014},
        "kosdaq": {"close": 887.81,  "change": -21.46, "change_pct": -2.36, "volume": 626829439},
        "foreign_net": None,
        "institution_net": None,
        "top_gainers": [
            {"name": "SK",        "change_pct": 20.51},
            {"name": "SK하이닉스", "change_pct": 13.06},
            {"name": "삼성전자우", "change_pct": 10.07},
            {"name": "삼성물산",   "change_pct":  7.79},
            {"name": "SK스퀘어",   "change_pct":  5.56},
        ],
        "top_losers": [
            {"name": "LG에너지솔루션", "change_pct": -3.69},
            {"name": "두산에너빌리티", "change_pct": -3.09},
            {"name": "LS ELECTRIC",   "change_pct": -2.45},
            {"name": "한화에어로스페이스","change_pct": -2.29},
            {"name": "효성중공업",     "change_pct": -2.18},
        ],
        "top_sectors": [],
        "bottom_sectors": [],
        "news": [],
    }

    post = generate_post(sample)
    print("\n── 생성된 포스트 ──")
    print(f"제목: {post['title']}")
    print(f"라벨: {post['labels']}")
    print(f"글자수: {post['char_count']}")
    print("\n── HTML 본문 ──")
    print(post["content"])
