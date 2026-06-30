# -*- coding: utf-8 -*-
import re
from anthropic import Anthropic
from shared.utils import DISCLAIMER, md_to_html, apply_color_spans

client = Anthropic()


def _match_news(name: str, headlines: list, stock_news_map: dict) -> str:
    """종목별 뉴스 맵 우선 조회 → fallback: 헤드라인 리스트 검색."""
    if name in stock_news_map:
        return stock_news_map[name]
    for h in headlines:
        if name in h:
            return h
    return ""


def _build_stock_anchor(data: dict) -> str:
    gainers = data.get("top_gainers", [])
    losers = data.get("top_losers", [])
    headlines = data.get("crawled_news_features", [])
    stock_news_map = data.get("stock_news_map", {})
    lines = []
    non_upper = []

    if gainers:
        parts = []
        for s in gainers:
            if s.get("is_upper_limit"):
                label = " [상한가]"
            else:
                label = ""
                non_upper.append(s["name"])
            matched = _match_news(s["name"], headlines, stock_news_map)
            news_tag = f" [뉴스근거: {matched}]" if matched else " [뉴스없음: 이유항목 완전삭제, 종목명+등락률만 표기]"
            parts.append(f"{s['name']} {s['change_pct']:+.2f}%{label}{news_tag}")
        lines.append("급등:\n" + "\n".join(parts))

    if losers:
        parts = []
        for s in losers:
            matched = _match_news(s["name"], headlines, stock_news_map)
            news_tag = f" [뉴스근거: {matched}]" if matched else " [뉴스없음: 이유항목 완전삭제, 종목명+등락률만 표기]"
            parts.append(f"{s['name']} {s['change_pct']:+.2f}%{news_tag}")
        lines.append("급락:\n" + "\n".join(parts))

    result = "\n".join(lines) if lines else "(종목 데이터 없음)"
    if non_upper:
        result += f"\n⚠️ 상한가 표현 절대 금지 종목: {', '.join(non_upper)}"
    return result


def _build_sector_anchor(data: dict) -> str:
    top = data.get("top_sectors", [])
    bot = data.get("bottom_sectors", [])
    lines = []

    def _sector_line(s):
        base = f"{s['name']} {s['change_pct']:+.2f}%"
        stocks = s.get("top_stocks", [])
        if stocks:
            stock_str = ", ".join(f"{t['name']}({t['change_pct']:+.2f}%)" for t in stocks)
            return f"{base} [관련종목: {stock_str}]"
        return base

    if top:
        lines.append("상승 섹터: " + " | ".join(_sector_line(s) for s in top))
    if bot:
        lines.append("하락 섹터: " + " | ".join(_sector_line(s) for s in bot))
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

[당일 특징주 등락률 — 수치를 한 글자도 바꾸지 말 것]{stocks_skip_note}
{stock_anchor}

[당일 섹터 등락률 + 관련 종목 — 수치 그대로 사용, 관련종목은 테이블 대표종목 컬럼에만 사용]
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
6. 이유 출처: 뉴스 헤드라인에 있는 팩트만. 헤드라인에 없으면 이유 항목 자체를 완전 삭제.
   - 테마명·섹터명 임의 생성 절대 금지 (예: "호남 반도체 테마주", "AI 수혜주" 등 데이터에 없는 표현 금지)
   - "— 이유 없음", "— 정보 없음", "— 특정 뉴스 영향", "— 관련 이슈", "— 시장 변동성" 등 구체성 없는 표현 금지. 이유가 없으면 종목명(등락률)만 표기.
   - 기관명·단체명·정책명 임의 생성 절대 금지. 뉴스 헤드라인에 없는 기관명은 절대 쓰지 말 것 (예: 임의로 만든 기관명 금지).
   - "상한가" 표현은 데이터 블록에 [상한가] 태그가 붙은 종목에만 사용. 태그 없으면 "급등", "강세" 등으로 표현.
   - 시황·지수 전체 흐름 헤드라인(예: "코스피 8500선 앞두고 강세", "상반기 마감" 등)을 개별 종목 이유로 사용 금지.
     개별 종목 이유는 해당 종목 자체에 관한 내용만. 지수·시황 헤드라인이 매칭됐어도 이유 항목 삭제.
   - 수급 방향 표현 일치 필수: 하락 종목에 "수급 유입", "매수 유입", "수급 이동(유입)" 표현 금지.
     하락 종목 수급은 "수급 이탈", "매도 우위" 등 하락 방향으로만 표현.
7. 분량: 마크다운 텍스트 기준 1500~2500자.
9. {direction_rule}
10. 맞춤법 규칙: 외래어 표기법 준수. 오타 절대 금지. (예: 포지셔닝, 리밸런싱, 모멘텀, 섹터)
11. 전망 섹션 제한: 당일 데이터(지수·섹터·뉴스)에서 직접 도출되는 내용만 언급할 것.
    - 금지: 데이터에 없는 매크로 단정 ("고금리 환경", "경기침체 우려", "펀더멘털 재정렬" 등)
    - 금지: 특정 섹터·종목 매수·매도 권유 성격의 표현
    - 허용: 오늘 수급·섹터 흐름을 근거로 한 추세 서술
12. 레이아웃 구조 고정: 반드시 ### 섹션 3개만(📊 1. / 💥 2. / 🔮 3.) 유지. 섹션 추가·삭제·번호 변경·재배치 절대 금지.
    - [당일 주도 섹터 및 테마]는 반드시 '### 📊 1. 시장 지표 및 수급 종합' 내 #### 하위 섹션으로만 위치.
    - 데이터 없어도 섹션 구조는 유지.
13. TITLE 방향 표현: KOSPI 기준으로만 결정. "혼조" 단어 절대 금지.
    - KOSPI 상승일 → "상승 마감", "강세", "반등" 등 상승 표현만 사용.
    - KOSDAQ이 반대 방향이어도 제목에서 "혼조"로 표현하지 말 것.
14. 섹터·종목 설명 방향 일치 규칙 (반드시 준수 — 작성 후 부호 재확인 필수):
    - 등락률 마이너스(-) 섹터/종목: "하락", "약세", "낙폭", "하락폭" 표현만.
      ❌ 절대 금지: "상승폭을 제한", "상승 탄력을 낮췄다", "상승을 방어"
    - 등락률 플러스(+) 섹터/종목: "상승", "강세", "상승폭" 표현만.
      ❌ 절대 금지: "낙폭을 제한", "하락을 방어"
    - 체크: 각 항목 작성 후 등락률 부호와 표현 방향이 일치하는지 반드시 검토할 것.

[출력 레이아웃 — 반드시 이 구조로 출력]

## [{date_title} 국내증시] 주도섹터 + 대장종목 + 수치

📌 **오늘 시장 핵심** (구글 검색 설명으로 노출됨 — 날짜·코스피·코스닥 등락률·핵심 종목/섹터 키워드를 첫 2문장 안에 반드시 포함. 이모티콘 제외 150자 이내로 압축):
KOSPI·KOSDAQ 수치 포함 2~3문장 요약.

---

### 📊 1. 시장 지표 종합

#### [국내 증시 마감 지수]
| 지수명 | 마감 지수 | 등락률 | 주요 움직임 |
| :--- | :--- | :--- | :--- |
| **KOSPI** | [마감지수pt] | [색상태그 포함 등락률] | [명사형 한 줄 요약 — 예: "반도체·전자장비 강세로 상반기 반등 마감"] |
| **KOSDAQ** | [마감지수pt] | [색상태그 포함 등락률] | [명사형 한 줄 요약 — 예: "바이오·화학 약세로 상승 탄력 제한"] |

#### [당일 주도 섹터 및 테마]
| 주도 섹터 | 등락률 | 대표 종목 | 핵심 흐름 한 줄 |
| :--- | :--- | :--- | :--- |
| [상위섹터1] | [색상태그 포함] | [관련종목 데이터의 종목명만 1~2개, 없으면 — ] | [섹터 흐름 한 줄] |
| [상위섹터2] | [색상태그 포함] | ... | ... |
| [하위섹터1] | [색상태그 포함] | ... | ... |

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

오늘 섹터·특징주 흐름을 근거로 2~3문장. 과도한 낙관·비관 금지.
데이터에 없는 매크로("고금리 환경" 등) 단정 금지. 불확실성은 "~가능성이 있습니다" 어조 사용.

---

출력 형식 — 아래 3줄 헤더 뒤에 마크다운 본문만 작성 (면책 조항은 포함하지 말 것. 시스템이 자동 추가):
TITLE: 핵심내용만 (날짜 prefix 없이 핵심내용만 출력 — 예: "반도체 강세로 KOSPI 상승, 전자장비·바이오주 주도")
  - 핵심내용은 오늘 지수 등락률·상위 섹터명·대장 종목명만 사용. 임의 조어·축약어·한자 조합 절대 금지.
  - HTML 태그 없는 순수 텍스트. 대괄호 [] 사용 금지.
CONTENT:
[마크다운 본문]"""

    return prompt


def _strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def _build_labels(data: dict) -> list:
    base = ["코스피", "코스닥", "시황", "주식", "오늘증시", "특징주"]
    sector_labels = [s["name"] for s in data.get("top_sectors", [])[:2]]
    return base + sector_labels


def _make_date_prefix(date: str) -> str:
    """'2026-06-30' → '[26년 6월 30일 국내증시]'"""
    try:
        from datetime import datetime as _dt
        _d = _dt.strptime(date, "%Y-%m-%d")
        return f"[{str(_d.year)[2:]}년 {_d.month}월 {_d.day}일 국내증시]"
    except Exception:
        return f"[{date} 국내증시]" if date else ""


def _parse_response(raw: str, date: str = "") -> dict:
    title = ""
    content_lines = []
    in_content = False
    date_prefix = _make_date_prefix(date)

    for line in raw.split("\n"):
        if line.startswith("TITLE:"):
            raw_title = _strip_html(line.removeprefix("TITLE:").strip())
            # AI가 붙인 대괄호 prefix 제거 후 Python prefix 강제 삽입
            raw_title = re.sub(r"^\[[^\]]*\]\s*", "", raw_title)
            title = f"{date_prefix} {raw_title}".strip() if date_prefix else raw_title
        elif line.startswith("CONTENT:"):
            in_content = True
        elif in_content:
            content_lines.append(line)

    content = apply_color_spans(md_to_html("\n".join(content_lines).strip())) + "\n" + DISCLAIMER
    return {"title": title, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-haiku-4-5-20251001") -> dict:
    prompt = _build_prompt(data)
    date = data.get("date", "")

    for attempt in range(3):
        message = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text
        result = _parse_response(raw, date=date)
        result["labels"] = _build_labels(data)
        print(f"  [작성] 제목: {result['title']}")
        print(f"  [작성] 글자수: {result['char_count']}자  라벨: {result['labels']}")

        if result["title"] and result["char_count"] > 500:
            return result

        # 파싱 실패 — 원인 파악용 원본 응답 출력
        print(f"  [재시도 {attempt + 1}/3] TITLE/CONTENT 파싱 실패. AI 응답 앞 300자:")
        print(f"  {raw[:300]}")

    raise RuntimeError("AI 응답 파싱 3회 모두 실패 — 발행 중단")
