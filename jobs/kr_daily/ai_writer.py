# -*- coding: utf-8 -*-
import os
from anthropic import Anthropic

client = Anthropic()


def _fmt_won(amount) -> str:
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


def _build_stock_anchor(data: dict) -> str:
    gainers = data.get("top_gainers", [])
    losers = data.get("top_losers", [])
    lines = []
    if gainers:
        lines.append("급등: " + " | ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in gainers))
    if losers:
        lines.append("급락: " + " | ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in losers))
    return "\n".join(lines) if lines else "(종목 데이터 없음)"


def _build_sector_anchor(data: dict) -> str:
    top = data.get("top_sectors", [])
    bot = data.get("bottom_sectors", [])
    lines = []
    if top:
        lines.append("상승 섹터: " + " | ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in top))
    if bot:
        lines.append("하락 섹터: " + " | ".join(f"{s['name']} {s['change_pct']:+.2f}%" for s in bot))
    return "\n".join(lines) if lines else "(섹터 데이터 없음 — 섹터 등락률 언급 금지)"


def _build_news_anchor(headlines: list, stock_pct_map: dict = None) -> str:
    if not headlines:
        return "(특징주 뉴스 없음 — 이유 항목 생략하고 종목명(등락률) 형식으로만 작성)"
    lines = []
    for i, h in enumerate(headlines[:15]):
        pct_tag = ""
        if stock_pct_map:
            for name, pct in stock_pct_map.items():
                if name in h:
                    pct_tag = f" [{pct:+.2f}%]"
                    break
        lines.append(f"{i + 1}. {h}{pct_tag}")
    return "\n".join(lines)


def _build_prompt(data: dict) -> str:
    date = data.get("date", "")
    kospi = data.get("kospi", {})
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

    foreign = data.get("foreign_net")
    institution = data.get("institution_net")
    investor_section = ""
    if foreign is not None:
        investor_section = (
            f"외국인: {_fmt_won(abs(foreign))} {_direction(foreign)}\n"
            f"기관:   {_fmt_won(abs(institution))} {_direction(institution)}"
        )

    stock_anchor = _build_stock_anchor(data)
    sector_anchor = _build_sector_anchor(data)
    news_anchor = _build_news_anchor(data.get("crawled_news_features", []), data.get("stock_pct_map", {}))

    base_labels = ["코스피", "코스닥", "시황", "주식", "오늘증시", "특징주"]
    sector_labels = [s["name"] for s in data.get("top_sectors", [])[:2]]
    all_labels = ",".join(base_labels + sector_labels)

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

[작성 지침]

1. 실시간 뉴스 기반 상승/하락 이유 매칭 (최우선)
- 위 [특징주] 뉴스 헤드라인을 철저히 분석하여 당일 주요 종목을 추출하세요.
- 반드시 종목명(등락률) — 이유 형태로 리스트를 구성해야 합니다.
- 절대 이유를 임의로 지어내지 마세요(환각 금지). 오직 제공된 뉴스 헤드라인에 명시된 팩트만 사용.
- 뉴스 헤드라인에 이유가 없는 종목은 이유 항목을 생략하고 종목명(등락률)만 표기.

2. 환각 방지 (절대 규칙)
A. 등락률 수치는 위 데이터 블록의 값만 사용. 임의 창작 금지.
B. 상승/하락 이유는 제공된 뉴스 헤드라인에 근거한 팩트만 사용.
C. 수급 데이터 없으면 수급 관련 문장 작성 금지.

작성 규칙:
1. HTML 형식 (Blogger에 바로 붙여 넣는 포맷). 마크다운(###) 사용 금지.
2. 분량: HTML 태그 포함 2000~2800자
3. 스마트폰 가독성: 모든 <p> 태그는 2~3문장 이내로 짧게.
4. 어조: 전문적이고 정중한 톤앤매너(~입니다, ~로 분석됩니다).

구조 (반드시 이 순서로):
a) <h2> 제목: "[{date_title} 시황] 주도섹터 + 대장종목명 + 수치" 형식
b) <h3>📌 오늘 시장 핵심</h3> — 지수·섹터·특징주를 아우르는 2~3문장 요약. KOSPI/KOSDAQ 수치 필수 포함.
c) <h3>📈 지수 동향</h3> — KOSPI/KOSDAQ 각각 별도 <p>로 수치 포함 서술. 수급 데이터 없으면 수급 문장 절대 금지.
d) <h3>🔥 당일 주도 섹터 및 특징주</h3>
   - 섹터 흐름 1~2문장 (섹터명 + 등락률 포함)
   - 급등 종목 앞에 반드시 <p><strong>📈 상승 특징주</strong></p> 소제목 출력
   - 급락 종목 앞에 반드시 <p><strong>📉 하락 특징주</strong></p> 소제목 출력
   - 각 특징주를 <ul><li>종목명(등락률) — 이유</li></ul> 형식으로 기술
   - 마지막 <p>에 SeedUP 인사이트: 오늘 데이터에서 투자자 관점 핵심 관찰 1~2가지
e) <h3>🔮 내일 시장 전망</h3> — 신중한 어조로 2~3문장
f) 면책 문구 — h3/h4 제목 없이 아래 문구를 <p> 태그로만 출력 (한 글자도 바꾸지 말 것):
   <p style="margin-top:30px; padding:15px; background:#f5f5f5; border-left:4px solid #999; font-size:12px; color:#666;">⚠️ 본 포스트는 시장 정보 제공 및 교육 목적으로 작성된 것이며, 어떤 식으로든 특정 종목 또는 금융상품의 매매를 추천하는 것이 아닙니다. 투자 결정은 반드시 개인의 투자 목표, 위험 선호도, 재무 상황을 고려하여 신중히 진행하시기 바랍니다. SeedUP 투자 블로그는 본 내용으로 인한 모든 직·간접적 손실에 대해 책임을 지지 않습니다. ⚠️</p>

출력 형식 — 아래 3줄 헤더 뒤에 HTML 본문만 작성 (다른 설명 없음):
TITLE: [{date_title} 시황] 핵심내용
LABELS: {all_labels}
CONTENT:
[HTML 본문]"""

    return prompt


def _parse_response(raw: str) -> dict:
    title = ""
    labels = []
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
    return {"title": title, "labels": labels, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-haiku-4-5-20251001") -> dict:
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
