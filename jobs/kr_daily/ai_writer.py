# -*- coding: utf-8 -*-
import re
from anthropic import Anthropic
from shared.utils import DISCLAIMER, KR_REPORT_LINKS_HTML, md_to_html, apply_color_spans, fix_weekday_labels, next_kr_trading_day_label

client = Anthropic()


def _build_stock_anchor(data: dict) -> str:
    gainers = data.get("top_gainers", [])
    losers = data.get("top_losers", [])
    # 3단계 검증 완료 목록 (data_collector.extract_and_verify_featured_stocks 결과)
    featured_verified = data.get("featured_verified", [])

    lines = []
    non_upper = []
    main_names = {s["name"] for s in gainers + losers}

    if gainers:
        parts = []
        for s in gainers:
            if s.get("is_upper_limit"):
                label = " [상한가]"
            else:
                label = ""
                non_upper.append(s["name"])
            parts.append(f"{s['name']} {s['change_pct']:+.2f}%{label}")
        lines.append("상승 특징주 (종목명+등락률만 — 이유 작성 절대 금지):\n" + "\n".join(parts))

    if losers:
        parts = []
        for s in losers:
            parts.append(f"{s['name']} {s['change_pct']:+.2f}%")
        lines.append("하락 특징주 (종목명+등락률만 — 이유 작성 절대 금지):\n" + "\n".join(parts))

    # 뉴스기반 특징주: Python 검증 완료 종목만.
    # data_collector.collect_all()이 뉴스기반 검증을 먼저 확정한 뒤 그 종목을
    # 제외하고 TOP5를 뽑으므로 정상 흐름에서는 겹치지 않는다. 아래 필터는
    # 그래도 중복이 발생하는 예외 상황에 대비한 이중 안전장치다.
    news_stocks = [
        f"{v['name']} {v['change_pct']:+.2f}% [뉴스: {v['news']}]"
        for v in featured_verified
        if v["name"] not in main_names
    ]

    if news_stocks:
        lines.append("뉴스기반 특징주 (이 목록 종목만 이유 작성 가능):\n" + "\n".join(news_stocks))
    else:
        lines.append("뉴스기반 특징주: (없음 — 📰 뉴스기반 특징주 섹션 생략)")

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
            base = f"{base} [관련종목: {stock_str}]"
        if s.get("theme_isolated"):
            base += " ⚠️[개별종목 테마성 이슈 — 업종 전반 이슈 아님, '동반 강세/약세' 표현 금지]"
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

    next_day_label = next_kr_trading_day_label(date)

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
6. 특징주 섹션별 이유 작성 규칙:
   - 📈 상승 특징주 / 📉 하락 특징주: 이유 작성 절대 금지. 종목명과 등락률만 표기.
     ❌ 금지 예시: "— 대장주 활약", "— 상한가 직행", "— 수급 유입", "— 업황 호조" 등 일절 금지.
   - 📰 뉴스 기반 특징주: 데이터 블록 '뉴스기반 특징주' 목록에 있는 종목만 이유 작성 가능.
     이유는 반드시 해당 종목의 [뉴스] 태그 내용에서만 추출. 목록에 없는 내용 임의 추가 금지.
     목록이 없으면 이 섹션 전체 생략.
     ⚠️ 종목명이 뉴스에서 "계약 상대방"·"피인수 대상" 등 타 회사의 행위 대상으로만 언급된 경우
     (예: "OO전자와의 공급 계약"처럼 종목 자신이 계약 주체가 아닌 경우) 절대 자기 자신의
     행위처럼 서술하지 말 것. 문장 주어와 종목명이 일치하지 않으면 그 종목은 이유 작성 없이
     "동반 강세를 보였습니다" 등 중립적 표현만 사용하거나 해당 종목 항목 자체를 생략할 것.
   - [당일 주도 섹터 및 테마] 표의 "대표 종목"에 ⚠️[개별종목 테마성 이슈] 표시가 붙어 있으면,
     그 종목의 급등락이 섹터/업종 전반의 흐름이 아니라 그 종목만의 개별 이슈(테마 편입,
     개별 계약·공시 등)일 가능성이 높다는 뜻이다. 이 경우 "OO 섹터 동반 강세/약세",
     "업종 전반 강세" 같은 표현을 쓰지 말고 "OO 섹터는 [종목명]의 개별 강세에 힘입어
     상승했으나 업종 전반 확산 여부는 불확실합니다" 처럼 대표종목 1개의 상승과 섹터
     전체를 분리해서 서술할 것.
   - 공통 금지 사항:
     - 테마명·섹터명 임의 생성 금지 (예: "호남 반도체 테마주", "AI 수혜주" 등 데이터에 없는 표현 금지)
     - 기관명·단체명·정책명 임의 생성 금지. 뉴스 헤드라인에 없는 기관명 절대 금지.
     - "상한가" 표현은 데이터 블록에 [상한가] 태그가 붙은 종목에만 사용. 태그 없으면 "급등", "강세" 표현.
     - 시황·지수 전체 흐름 헤드라인을 개별 종목 이유로 사용 금지.
     - 수급 방향 표현 일치: 하락 종목에 "수급 유입", "매수 유입" 표현 금지.
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
    - 등락률 마이너스(-) 섹터/종목 자체는 "하락", "약세", "낙폭" 표현으로만 서술.
      ❌ 금지: 마이너스 종목을 "상승", "강세", "반등"으로 서술하는 방향 오류.
    - 등락률 플러스(+) 섹터/종목 자체는 "상승", "강세" 표현으로만 서술.
      ❌ 금지: 플러스 종목을 "하락", "약세", "부진"으로 서술하는 방향 오류.
    - 단, 그 섹터·종목이 '지수'에 미친 영향(예: "KOSPI 상승폭을 제한했다", "낙폭을 방어했다")은
      규칙 9의 표현만 따른다. 규칙 9와 이 규칙이 충돌하는 것처럼 보이면 규칙 9 우선.
    - 체크: 각 항목 작성 후 등락률 부호와 표현 방향이 일치하는지 반드시 검토할 것.
15. '내일' 단어 사용 절대 금지 (다음 거래일이 내일이 아닐 수 있음 — 주말·공휴일 존재).
    다음 거래일을 언급할 때는 반드시 '{next_day_label}'로 표기할 것. 직접 요일 계산 금지.
16. 어조: 전문적이고 정중한 존댓말(~입니다, ~했습니다). 반말체(~했다, ~이다) 절대 금지.
17. 문체 규칙 (기계적 반복 금지):
    - '~로 분석됩니다', '~로 판단됩니다', '~로 보입니다'는 각각 글 전체에서 1회 이하.
    - 같은 종결어미 3문장 연속 금지 — 단, 변주는 반드시 존댓말 범위 안에서만
      (예: ~했습니다 / ~입니다 / ~습니다 를 섞기). 한 문단 안에 짧은 문장을 1개 이상 섞을 것.
    - 이모지는 지정된 소제목·리스트 외 본문 문장에 추가 금지.
    - '한편', '또한'으로 시작하는 문단은 2개 이하.
18. 각 표 바로 아래에 표를 해석하는 연결 문장 1개를 넣을 것.
    표 수치 반복 금지 — '이 수치가 무엇을 의미하는가'만 서술. 근거는 위 데이터·뉴스 블록으로 한정.

[출력 레이아웃 — 반드시 이 구조로 출력]
(제목은 위 TITLE: 필드로 별도 출력됨 — 본문 첫 줄에 ## 제목 헤딩 절대 추가 금지)

📌 **오늘 시장 핵심** (구글 검색 설명으로 노출됨 — 날짜·코스피·코스닥 등락률·핵심 종목/섹터 키워드를 첫 2문장 안에 반드시 포함. 이모티콘 제외 150자 이내로 압축):
KOSPI·KOSDAQ 수치 포함 2~3문장 요약.
첫 문장 규칙: "코스피는~", "오늘 증시는~"으로 시작 금지. 날짜와 함께, 오늘 데이터에서
가장 눈에 띄는 것 1가지(최대 등락 섹터·상한가 종목·특징주 급등락 등)를 구체적 수치와
함께 첫 문장에 배치할 것. 지수 종합 수치는 두 번째 문장부터. (데이터 블록에 없는 내용 금지)

---

### 📊 1. 시장 지표 종합

#### [국내 증시 마감 지수]
| 지수명 | 마감 지수 | 등락률 | 주요 움직임 |
| :--- | :--- | :--- | :--- |
| **KOSPI** | [마감지수pt] | [색상태그 포함 등락률] | [명사형 한 줄 요약 — 예: "반도체·전자장비 강세로 상반기 반등 마감"] |
| **KOSDAQ** | [마감지수pt] | [색상태그 포함 등락률] | [명사형 한 줄 요약 — 예: "바이오·화학 약세로 상승 탄력 제한"] |

[표 해석 문장 1개 — 규칙 18: 수치 반복 금지, 두 지수 흐름의 의미만]

#### [당일 주도 섹터 및 테마]
| 주도 섹터 | 등락률 | 대표 종목 | 핵심 흐름 한 줄 |
| :--- | :--- | :--- | :--- |
| [상위섹터1] | [색상태그 포함] | [관련종목 데이터의 종목명(등락률) 1~2개 — 예: 삼화전자(+29.88%), 없으면 — ] | [섹터 흐름 한 줄] |
| [상위섹터2] | [색상태그 포함] | ... | ... |
| [하위섹터1] | [색상태그 포함] | ... | ... |

[표 해석 문장 1개 — 규칙 18: 수치 반복 금지, 섹터 흐름의 의미만]

---

### 💥 2. 오늘 시장의 특징주

#### 📈 상승 특징주
- **[종목A]** <span style="color:#e74c3c"><b>+X.XX%</b></span>
- **[종목B]** <span style="color:#e74c3c"><b>+X.XX%</b></span>

#### 📉 하락 특징주
- **[종목X]** <span style="color:#3182f6"><b>-X.XX%</b></span>
- **[종목Y]** <span style="color:#3182f6"><b>-X.XX%</b></span>

#### 📰 뉴스 기반 특징주
(데이터 블록 '뉴스기반 특징주'에 있는 종목만 작성. 없으면 이 섹션 전체 생략.)
- **[종목명]** <span style="color:#e74c3c"><b>+X.XX%</b></span> — [해당 종목 [뉴스] 내용에서만 추출한 이유]

---

### 🔮 3. 다음 거래일 전망 ({next_day_label})

오늘 섹터·특징주 흐름을 근거로 2~3문장. 과도한 낙관·비관 금지.
데이터에 없는 매크로("고금리 환경" 등) 단정 금지. 불확실성은 "~가능성이 있습니다" 어조 사용
(단, "~가능성이 있습니다"로 2문장 연속 종결 금지).
마지막 문장은 {next_day_label}에 확인할 체크포인트 1가지(오늘 주도 섹터의 지속 여부,
특정 지수선 유지 여부 등 오늘 데이터에서 도출되는 것)를 관찰형으로 제시할 것.
'내일' 대신 반드시 '{next_day_label}' 표현 사용.

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
    base = ["코스피", "코스닥", "시황", "주식", "오늘증시", "특징주", "국내데일리"]
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
    found_content_marker = False
    title_line_idx = None

    lines = raw.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("TITLE:"):
            raw_title = _strip_html(line.removeprefix("TITLE:").strip())
            # AI가 붙인 대괄호 prefix 제거 후 Python prefix 강제 삽입
            raw_title = re.sub(r"^\[[^\]]*\]\s*", "", raw_title)
            title = f"{date_prefix} {raw_title}".strip() if date_prefix else raw_title
            title_line_idx = i
        elif line.startswith("CONTENT:"):
            in_content = True
            found_content_marker = True
        elif in_content:
            content_lines.append(line)

    if not found_content_marker:
        # AI가 CONTENT: 마커를 누락한 경우 — TITLE: 다음 줄부터 전체를 본문으로 처리
        start = title_line_idx + 1 if title_line_idx is not None else 0
        content_lines = lines[start:]
        print("  [파싱 경고] CONTENT: 마커 누락 — TITLE: 다음 줄부터 전체를 본문으로 대체 처리")

    # 본문 첫 헤딩이 제목과 중복되면 제거 (AI가 지침 무시하고 #~###### 헤딩으로 제목 반복하는 케이스)
    md_body = "\n".join(content_lines).strip()
    first_line = md_body.split("\n", 1)[0] if md_body else ""
    if re.match(r"^#{1,6}\s", first_line) and ("국내증시]" in first_line or (date_prefix and date_prefix in first_line)):
        md_body = md_body.split("\n", 1)[1].strip() if "\n" in md_body else ""
        print("  [후처리] 본문 첫 줄 제목 중복 헤딩 제거")

    if date:
        md_body = fix_weekday_labels(md_body, date)

    content = apply_color_spans(md_to_html(md_body)) + "\n" + DISCLAIMER + "\n" + KR_REPORT_LINKS_HTML
    return {"title": title, "content": content, "char_count": len(content)}


def generate_post(data: dict, model: str = "claude-sonnet-4-6") -> dict:
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
