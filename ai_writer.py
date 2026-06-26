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


# ── 데이터 앵커 빌더 (AI 수치 환각 방지) ─────────────────────────────────

def _build_stock_anchor(data: dict) -> str:
    """급등/급락 종목 등락률 — AI에게 수치 앵커로 제공"""
    gainers = data.get("top_gainers", [])
    losers  = data.get("top_losers",  [])
    lines = []
    if gainers:
        lines.append("급등: " + " | ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in gainers))
    if losers:
        lines.append("급락: " + " | ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in losers))
    return "\n".join(lines) if lines else "(종목 데이터 없음)"


def _build_sector_anchor(data: dict) -> str:
    """섹터 등락률 — AI에게 수치 앵커로 제공"""
    top = data.get("top_sectors", [])
    bot = data.get("bottom_sectors", [])
    lines = []
    if top:
        lines.append("상승 섹터: " + " | ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in top))
    if bot:
        lines.append("하락 섹터: " + " | ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in bot))
    return "\n".join(lines) if lines else "(섹터 데이터 없음 — 섹터 등락률 언급 금지)"


def _build_news_anchor(headlines: list) -> str:
    """[특징주] 헤드라인 목록 → 번호 목록 텍스트"""
    if not headlines:
        return "(특징주 뉴스 없음 — 이유 항목 생략하고 [종목명 - 등락률] 형식으로만 작성)"
    return "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headlines[:15]))


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

    foreign     = data.get("foreign_net")
    institution = data.get("institution_net")
    investor_section = ""
    if foreign is not None:
        investor_section = (
            f"외국인: {_fmt_won(abs(foreign))} {_direction(foreign)}\n"
            f"기관:   {_fmt_won(abs(institution))} {_direction(institution)}"
        )

    stock_anchor  = _build_stock_anchor(data)
    sector_anchor = _build_sector_anchor(data)
    news_anchor   = _build_news_anchor(data.get("crawled_news_features", []))

    # 동적 라벨: 기본 6개 + 상승 섹터명 최대 2개
    base_labels   = ["코스피", "코스닥", "시황", "주식", "오늘증시", "특징주"]
    sector_labels = [s["name"] for s in data.get("top_sectors", [])[:2]]
    all_labels    = ",".join(base_labels + sector_labels)

    # 제목용 날짜 포맷: "2026-06-25" → "26년 6월 25일"
    try:
        from datetime import datetime as _dt
        _d = _dt.strptime(date, "%Y-%m-%d")
        date_title = f"{str(_d.year)[2:]}년 {_d.month}월 {_d.day}일"
    except Exception:
        date_title = date

    prompt = f"""당신은 대한민국 최고의 주식 리서치 분석가이자 구글 SEO(검색 최적화) 전문가입니다.
SeedUP INVEST 블로그(seedup-invest.blogspot.com)에 올릴 오늘({date}) 마감 시황 포스팅을 작성하세요.
블로그 설명: "매일 한국 주식 시황, 당일 주도 섹터 및 특징주 리포트. 시드머니를 키우는 가장 확실한 투자 인사이트, SeedUp INVEST"

━━━ 오늘의 시장 데이터 ━━━
{kospi_line}
{kosdaq_line}
{investor_section if investor_section else "(수급 데이터 미수집)"}

▼ 당일 특징주 등락률 (수치를 한 글자도 바꾸지 말고 그대로 사용할 것):
{stock_anchor}

▼ 당일 섹터 등락률 (수치 그대로 사용):
{sector_anchor}

▼ 당일 [특징주] 뉴스 헤드라인 (이 목록 기반으로만 상승/하락 이유를 작성할 것. 목록에 없는 종목·이유 추가 금지):
{news_anchor}
━━━━━━━━━━━━━━━━━━━━━━━━━━━

[새로운 작성 지침]

1. 실시간 뉴스 기반 상승/하락 이유 매칭 (최우선)
- 위 [특징주] 뉴스 헤드라인을 철저히 분석하여 당일 주요 종목을 추출하세요.
- 반드시 [종목명 - 등락률 - 상승/하락 이유] 형태로 리스트를 구성해야 합니다.
- 절대 이유를 임의로 지어내지 마세요(환각 금지). 오직 제공된 뉴스 헤드라인에 명시된 팩트에만 근거하세요.
- 뉴스 헤드라인에 이유가 없는 종목은 이유 항목을 생략하고 [종목명 - 등락률]만 표기하세요.

2. 구글 애드센스 고단가 키워드 필수 노출
- 당일 주도 종목명과 핵심 섹터명을 본문 전체에 최소 3~5회 이상 자연스럽게 반복 노출하세요.
- "일부 대형주", "주요 기술 기업" 같은 애매한 표현은 절대 쓰지 말고 정확한 기업명을 사용하세요.

3. 제목 최적화
- 당일 시장을 주도한 가장 강했던 섹터명과 대장 종목명을 제목에 반드시 포함하세요.

4. 환각 방지 (절대 규칙)
A. 등락률 수치는 위 데이터 블록의 값만 사용. 임의 창작 금지.
B. 상승/하락 이유는 제공된 뉴스 헤드라인에 근거한 팩트만 사용.
C. 헤드라인에 없는 외부 이벤트(Fed, 유가, 환율 등) 원인 추정 금지.
D. 수급 데이터(외국인·기관) 없으면 수급 관련 문장 작성 금지.

작성 규칙:
1. HTML 형식 (Blogger에 바로 붙여 넣는 포맷). 마크다운(###) 사용 금지.
2. 분량: HTML 태그 포함 2000~2800자
3. SEO: '코스피', '오늘 증시', '주식시장', '특징주' 키워드를 제목/본문에 자연스럽게 포함.
4. 스마트폰 가독성: 모든 <p> 태그는 2~3문장 이내로 짧게. 긴 단락은 반드시 쪼갤 것.
5. 어조: 전문적이고 정중한 톤앤매너(~입니다, ~로 분석됩니다).

구조 (반드시 이 순서로):
a) <h2> 제목: 반드시 "[{date_title} 시황] 주도섹터 + 대장종목명 + 수치" 형식
b) <h3>📌 오늘 시장 핵심</h3> — 지수·섹터·특징주를 아우르는 2~3문장 요약. KOSPI/KOSDAQ 수치 필수 포함.
c) <h3>📈 지수 동향</h3> — KOSPI/KOSDAQ 각각 별도 <p>로 수치 포함 서술. 수급 데이터 없으면 수급 문장 절대 금지.
d) <h3>🔥 당일 주도 섹터 및 특징주</h3>
   - 섹터 흐름 1~2문장 (섹터명 + 등락률 포함)
   - 각 특징주를 <ul><li>[종목명 - 등락률 - 이유]</li></ul> 형식으로 기술. 이유 없으면 [종목명 - 등락률]만.
   - 마지막 <p>에 SeedUP 인사이트: 오늘 데이터에서 투자자 관점 핵심 관찰 1~2가지
e) <h3>🔮 내일 시장 전망</h3> — 신중한 어조로 2~3문장
f) 면책 문구: h3/h4 제목 없이 아래 문구를 <p> 태그로만 출력 (한 글자도 바꾸지 말 것):
   <p style="margin-top:30px; padding:15px; background:#f5f5f5; border-left:4px solid #999; font-size:12px; color:#666;">⚠️ 본 포스트는 시장 정보 제공 및 교육 목적으로 작성된 것이며, 어떤 식으로든 특정 종목 또는 금융상품의 매매를 추천하는 것이 아닙니다. 투자 결정은 반드시 개인의 투자 목표, 위험 선호도, 재무 상황을 고려하여 신중히 진행하시기 바랍니다. SeedUP 투자 블로그는 본 내용으로 인한 모든 직·간접적 손실에 대해 책임을 지지 않습니다. ⚠️</p>

출력 형식 — 아래 3줄 헤더 뒤에 HTML 본문만 작성 (다른 설명 없음):
TITLE: [{date_title} 시황] 핵심내용 (예: [{date_title} 시황] 반도체 섹터 주도, SK하이닉스 +13.06% 신고가 랠리)
LABELS: {all_labels}
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
    sample = {
        "date": "2026-06-26",
        "kospi":  {"close": 9050.10, "change": 119.80, "change_pct": 1.34, "volume": 380000000},
        "kosdaq": {"close": 901.50,  "change": 13.69,  "change_pct": 1.54, "volume": 550000000},
        "foreign_net": None,
        "institution_net": None,
        "top_gainers": [
            {"name": "SK하이닉스",  "change_pct": 8.21},
            {"name": "삼성전자",    "change_pct": 5.43},
            {"name": "LG에너지솔루션", "change_pct": 4.12},
        ],
        "top_losers": [
            {"name": "한화에어로스페이스", "change_pct": -3.11},
            {"name": "두산에너빌리티",    "change_pct": -2.88},
        ],
        "top_sectors":    [{"name": "반도체", "change_pct": 6.30}, {"name": "IT서비스", "change_pct": 3.10}],
        "bottom_sectors": [{"name": "방산",   "change_pct": -2.50}],
        "news": [],
        "crawled_news_features": [
            "[특징주] SK하이닉스, HBM4 양산 일정 앞당겨…엔비디아 납품 확대 기대",
            "[특징주] 삼성전자, 3분기 영업이익 컨센서스 상회 전망에 외국인 순매수",
            "[특징주] LG에너지솔루션, 유럽 전기차 보조금 확대 수혜 기대감에 급등",
            "[특징주] 한화에어로스페이스, 방산 수출 계약 지연 소식에 차익 매물 출회",
        ],
    }

    post = generate_post(sample)
    print("\n── 생성된 포스트 ──")
    print(f"제목: {post['title']}")
    print(f"라벨: {post['labels']}")
    print(f"글자수: {post['char_count']}")
    print("\n── HTML 본문 ──")
    print(post["content"])
