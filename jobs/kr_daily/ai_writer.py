# -*- coding: utf-8 -*-
import re
from anthropic import Anthropic
from shared.utils import DISCLAIMER, md_to_html, fmt_amount

client = Anthropic()


def _build_investor_block(investor_top3: dict) -> str:
    """외국인/기관/연기금 순매수/순매도 TOP3 → 프롬프트용 텍스트 블록"""
    if not investor_top3:
        return "(수급 데이터 미수집)"
    lines = []
    for label, data in investor_top3.items():
        if isinstance(data, dict):
            buy = data.get("buy", [])
            sell = data.get("sell", [])
        else:
            buy = data if isinstance(data, list) else []
            sell = []
        buy_str = " | ".join(f"{s['name']}({fmt_amount(s['net_amount'])})" for s in buy) if buy else "(없음)"
        sell_str = " | ".join(f"{s['name']}({fmt_amount(s['net_amount'])})" for s in sell) if sell else "(없음)"
        lines.append(f"{label} 순매수: {buy_str}")
        lines.append(f"{label} 순매도: {sell_str}")
    return "\n".join(lines) if lines else "(수급 데이터 미수집)"


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
        return "(특징주 뉴스 없음 — 이유 항목 생략, 종목명(등락률) 형식으로만 작성)"
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

    investor_top3 = data.get("investor_top3", {})
    investor_block = _build_investor_block(investor_top3)
    investor_skip_note = (
        "\n⚠️ 수급 데이터 없음 → #### [메이저 수급 현황 (Top 3)] 소제목 포함 해당 섹션 전체 완전 삭제. 텍스트 한 줄도 출력 금지."
        if not investor_top3
        else ""
    )

    has_stocks = bool(data.get("top_gainers") or data.get("top_losers"))
    stocks_skip_note = (
        "\n⚠️ 특징주 데이터 없음 → ### 💥 2. 오늘 시장의 특징주 소제목 포함 해당 섹션 전체 완전 삭제. 텍스트 한 줄도 출력 금지."
        if not has_stocks
        else ""
    )

    stock_anchor = _build_stock_anchor(data)
    sector_anchor = _build_sector_anchor(data)
    news_anchor = _build_news_anchor(
        data.get("crawled_news_features", []), data.get("stock_pct_map", {})
    )

    base_labels = ["코스피", "코스닥", "시황", "주식", "오늘증시", "특징주"]
    sector_labels = [s["name"] for s in data.get("top_sectors", [])[:2]]
    all_labels = ",".join(base_labels + sector_labels)

    try:
        from datetime import datetime as _dt
        _d = _dt.strptime(date, "%Y-%m-%d")
        date_title = f"{str(_d.year)[2:]}년 {_d.month}월 {_d.day}일"
    except Exception:
        date_title = date

    kospi_up = kospi.get("change_pct", 0) > 0 if kospi else True
    direction_rule = (
        "⚠️ 오늘 KOSPI 상승일: '낙폭을 제한' 표현 절대 금지. "
        "약세 섹터·종목 설명 시 반드시 '상승폭을 제한했다' 또는 '상승 탄력을 낮췄다' 로 표현할 것."
        if kospi_up
        else
        "⚠️ 오늘 KOSPI 하락일: '상승폭을 제한' 표현 절대 금지. "
        "강세 섹터·종목 설명 시 반드시 '낙폭을 제한했다' 또는 '하락을 방어했다' 로 표현할 것."
    )

    prompt = f"""당신은 대한민국 최고의 주식 리서치 분석가이자 구글 SEO 전문가입니다.
SeedUP INVEST 블로그에 올릴 {date} 마감 국내 증시 시황 포스팅을 마크다운 형식으로 작성하세요.

━━━ 오늘의 시장 데이터 ({date}) ━━━

[지수]
{kospi_line}
{kosdaq_line}

[외국인/기관/연기금 수급 (KOSPI 기준)]{investor_skip_note}
{investor_block}

[당일 특징주 등락률 — 수치를 한 글자도 바꾸지 말 것]{stocks_skip_note}
{stock_anchor}

[당일 섹터 등락률 — 수치 그대로 사용]
{sector_anchor}

[당일 특징주 뉴스 헤드라인 — 이 목록 기반으로만 이유 작성. 목록에 없는 내용 추가 금지]
{news_anchor}
━━━━━━━━━━━━━━━━━━━━━━━━━━━

[필수 작성 규칙]
1. 출력 형식: 마크다운(markdown). 색상 인라인에만 HTML 태그 허용.
2. 수치 환각 절대 금지: 등락률·지수·수급 수치는 위 데이터 블록 값만 사용.
3. 색상 규칙 (모든 등락률 수치에 예외 없이 적용):
   - 플러스(상승): <span style="color:#e74c3c"><b>+X.XX%</b></span>
   - 마이너스(하락): <span style="color:#3182f6"><b>-X.XX%</b></span>
4. TITLE: 순수 텍스트만. HTML 태그 절대 금지.
5. ## ### #### 제목: 검정 텍스트만. color 태그 금지.
6. 이유 출처: 뉴스 헤드라인에 있는 팩트만. 없으면 이유 생략.
7. 수급 데이터가 "(없음)"인 행은 생략. 전체 없으면 #### [메이저 수급 현황 (Top 3)] 소제목 포함 해당 섹션 전체 완전 삭제. 텍스트 한 줄도 출력 금지.
8. 분량: 마크다운 텍스트 기준 1500~2500자.
9. {direction_rule}

[출력 레이아웃 — 반드시 이 구조로 출력]

## [{date_title} 국내증시] 주도섹터 + 대장종목 + 수치

📌 **오늘 시장 핵심** (구글 검색 설명으로 노출됨 — 날짜·코스피·코스닥 등락률·핵심 종목/섹터 키워드를 첫 2문장 안에 반드시 포함. 이모티콘 제외 150자 이내로 압축):
KOSPI·KOSDAQ 수치 포함 2~3문장 요약.

---

### 📊 1. 시장 지표 및 수급 종합

#### [국내 증시 마감 지수]
| 지수명 | 마감 지수 | 등락률 | 주요 움직임 |
| :--- | :--- | :--- | :--- |
| **KOSPI** | [마감지수pt] | [색상태그 포함 등락률] | [한 줄 흐름 요약] |
| **KOSDAQ** | [마감지수pt] | [색상태그 포함 등락률] | [한 줄 흐름 요약] |

#### [메이저 수급 현황 (Top 3)]
| 투자 주체 | 당일 순매수 상위 종목 | 당일 순매도 상위 종목 |
| :--- | :--- | :--- |
| **외국인** | [종목1], [종목2], [종목3] | [종목X], [종목Y], [종목Z] |
| **기관** | ... | ... |
| **연기금** | ... | ... |

#### [당일 주도 섹터 및 테마]
| 주도 섹터 | 등락률 | 핵심 관련주 및 흐름 |
| :--- | :--- | :--- |
| [상위섹터1] | [색상태그 포함] | [관련주 + 한 줄 흐름] |
| [상위섹터2] | [색상태그 포함] | ... |
| [하위섹터1] | [색상태그 포함] | ... |

---

### 💥 2. 오늘 시장의 특징주

#### 📈 상승 특징주
- **[종목A]** <span style="color:#e74c3c"><b>+X.XX%</b></span> — [뉴스 기반 이유]
- **[종목B]** <span style="color:#e74c3c"><b>+X.XX%</b></span> — [이유]

#### 📉 하락 특징주
- **[종목X]** <span style="color:#3182f6"><b>-X.XX%</b></span> — [뉴스 기반 이유]
- **[종목Y]** <span style="color:#3182f6"><b>-X.XX%</b></span> — [이유]

---

### 🔮 3. 내일 시장 전망

신중한 어조로 2~3문장. 과도한 낙관·비관 금지.

---

출력 형식 — 아래 3줄 헤더 뒤에 마크다운 본문만 작성 (면책 조항은 포함하지 말 것. 시스템이 자동 추가):
TITLE: [{date_title} 국내증시] 핵심내용 (HTML 태그 없는 순수 텍스트)
LABELS: {all_labels}
CONTENT:
[마크다운 본문]"""

    return prompt


def _strip_html(text: str) -> str:
    """제목에 섞인 HTML 태그 제거"""
    return re.sub(r'<[^>]+>', '', text).strip()


def _parse_response(raw: str) -> dict:
    title = ""
    labels = []
    content_lines = []
    in_content = False

    for line in raw.split("\n"):
        if line.startswith("TITLE:"):
            title = _strip_html(line.removeprefix("TITLE:").strip())
        elif line.startswith("LABELS:"):
            raw_labels = line.removeprefix("LABELS:").strip()
            labels = [l.strip() for l in raw_labels.split(",") if l.strip()]
        elif line.startswith("CONTENT:"):
            in_content = True
        elif in_content:
            content_lines.append(line)

    content = md_to_html("\n".join(content_lines).strip()) + "\n" + DISCLAIMER
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
