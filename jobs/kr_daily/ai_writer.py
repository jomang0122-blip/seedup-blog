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
    # 종목명 포함 필터를 통과한 검증된 헤드라인만 들어있음 (get_stock_news_by_name)
    stock_news_map = data.get("stock_news_map", {})

    def _news_tag(name):
        headline = stock_news_map.get(name, "")
        return f" [관련뉴스: {headline}]" if headline else ""

    if gainers:
        parts = []
        for s in gainers:
            if s.get("is_upper_limit"):
                label = " [상한가]"
            else:
                label = ""
                non_upper.append(s["name"])
            parts.append(f"{s['name']} {s['change_pct']:+.2f}%{label}{_news_tag(s['name'])}")
        lines.append("상승 특징주 (이유 문장 작성 금지 — [관련뉴스]는 명사형 구로 압축 요약해 병기):\n" + "\n".join(parts))

    if losers:
        parts = []
        for s in losers:
            parts.append(f"{s['name']} {s['change_pct']:+.2f}%{_news_tag(s['name'])}")
        lines.append("하락 특징주 (이유 문장 작성 금지 — [관련뉴스]는 명사형 구로 압축 요약해 병기):\n" + "\n".join(parts))

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
        breadth = s.get("breadth")
        if breadth:
            base += f" [업종폭: {breadth['total']}종목 중 {breadth['same_dir']}개 동방향 {breadth['ratio']:.0%}]"
        verdict = s.get("breadth_verdict")
        if verdict == "isolated":
            base += " ⚠️[소수 종목 견인 — 구성종목 과반이 반대/보합. '동반 강세/약세', '업종 전반' 표현 금지]"
        elif verdict == "broad":
            base += " [업종 전반 흐름 — 구성종목 60% 이상 같은 방향]"
        elif verdict == "mixed":
            base += " [혼재 — 같은 방향이 과반 근접. '동반'도 '개별 견인'도 단정 금지]"
        rep_news = [f"{t['name']} \"{t['news']}\"" for t in stocks if t.get("news")]
        if rep_news:
            base += f" [대표종목 뉴스: {' / '.join(rep_news)}]"
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



def _build_retry_feedback(prev_issues: list = None) -> str:
    """직전 시도의 검증 실패 사유를 다음 생성 프롬프트에 그대로 피드백한다.
    기존에는 needs_regenerate 시 완전히 동일한 프롬프트로 재시도해 같은 유형의
    창작이 자리만 바뀌어 반복되는 문제가 있었다(2026-07-13 dry-run 확인:
    1차 8건→2차 3건→3차 3건, 매번 목표가·공시 등 유사 패턴). 실패 사유를
    명시적으로 알려 같은 실수를 반복하지 않도록 한다."""
    if not prev_issues:
        return ""
    lines = [f"- [{i.get('type', '')}] {i.get('description', '')}" for i in prev_issues]
    return (
        "\n\n⚠️ 직전 시도에서 아래 문제로 반려됨 — 동일 실수 반복 금지, "
        "특히 데이터에 없는 구체적 사건·수치·목표가를 창작하지 말 것:\n"
        + "\n".join(lines)
    )


def _build_prompt(data: dict, prev_issues: list = None) -> str:
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
   - 📈 상승 특징주 / 📉 하락 특징주: "이유 문장"(~때문에, ~로 인해 식의 서술)
     작성 절대 금지. 종목명과 등락률만 표기.
     ❌ 금지 예시: "— 대장주 활약", "— 상한가 직행", "— 수급 유입", "— 업황 호조" 등 일절 금지.
     단, 데이터 블록에 [관련뉴스: ...]가 붙은 종목은 그 뉴스 내용을 짧은 명사형 구로
     요약해서 " — " 뒤에 붙일 것 — 예: "삼성전기 -8.09% — 엔비디아 AI 서버 지연설".
     괄호 "( )" 로 감싸지 말고, 반드시 아래 📰 뉴스 기반 특징주와 동일하게
     "종목명 등락률 — 요약구" 형식으로 통일할 것(대시 앞뒤 공백 포함).
     완결된 문장("~했습니다")이 아니라 다른 종목과 톤이 통일된 짧은 구로 쓸 것.
     "(관련뉴스: ...)" 라벨이나 원문 헤드라인을 그대로 노출하지 말고, 반드시
     핵심 키워드만 압축한 구로 재구성할 것. 단 뉴스에 없는 내용 추가는 금지.
     이 요약을 도입부·전망 등 다른 섹션의 서술 근거로 재사용하는 것도 금지
     (이 자리에서만 짧게 언급).
   - 📰 뉴스 기반 특징주: 데이터 블록 '뉴스기반 특징주' 목록에 있는 종목만 이유 작성 가능.
     이유는 반드시 해당 종목의 [뉴스] 태그 내용에서만 추출. 목록에 없는 내용 임의 추가 금지.
     목록이 없으면 이 섹션 전체 생략.
     문체: "~했습니다/~보였습니다" 같은 완결된 서술형 문장 금지. 상승/하락 특징주와
     톤을 통일해 짧은 명사형 구로 쓸 것 — 예: "삼성전자 +2.75% — 실적 발표 하루 앞두고
     기대감 유입" (❌ "기대감이 유입되며 강세를 보였습니다"). "~에", "~으로", "~속" 등
     연결어로 끝내고 종결어미(-다/-습니다)로 마무리하지 말 것.
     ⚠️ 종목명이 뉴스에서 "계약 상대방"·"피인수 대상" 등 타 회사의 행위 대상으로만 언급된 경우
     (예: "OO전자와의 공급 계약"처럼 종목 자신이 계약 주체가 아닌 경우) 절대 자기 자신의
     행위처럼 서술하지 말 것. 문장 주어와 종목명이 일치하지 않으면 그 종목은 이유 작성 없이
     "동반 강세를 보였습니다" 등 중립적 표현만 사용하거나 해당 종목 항목 자체를 생략할 것.
   - [당일 주도 섹터 및 테마] 서술 규칙 — 데이터 블록의 [업종폭] 표시가 판정 근거,
     [대표종목 뉴스]가 있으면 그 내용이 문장의 핵심 소재:
     - **[대표종목 뉴스]가 있는 섹터는 그 뉴스 내용을 반드시 문장에 녹여 쓸 것**
       (생략 금지 — 있는데도 판정 라벨만 쓰고 넘어가지 말 것). 원문을 그대로 붙이거나
       따옴표로 인용하지 말고 한 문장으로 자연스럽게 요약. 확대해석·인과 창작 금지.
     - [대표종목 뉴스]가 없는 섹터만 아래 판정 표시를 짧게 서술의 뼈대로 삼을 것.
       단 "동반 강세", "업종 내 등락 혼재" 같은 정해진 문구를 다른 섹터 행에도
       반복해서 붙이지 말 것 — 각 행마다 그 섹터의 등락률·구성 자체를 근거로
       표현을 다르게 쓸 것(예: 등락폭 크기, 대표종목 등락률 격차 등으로 변주).
     - ⚠️[소수 종목 견인] 표시: 구성종목 과반이 섹터와 반대/보합인데 소수 종목이 지수를
       움직인 것 — "동반 강세/약세", "업종 전반" 표현 금지.
     - [업종 전반 흐름] 표시: 구성종목 60% 이상 같은 방향 — "업종 전반 강세/약세" 서술
       가능. 굳이 "불확실" 같은 유보 표현을 붙이지 말 것.
     - [혼재] 표시: 같은 방향이 과반 근접 수준 — "동반 강세"도 "개별 종목 견인"도 단정
       하지 말고 사실대로 서술.
     - 아무 표시도 뉴스도 없는 섹터: 등락률과 대표종목 등락률 격차만으로 서술
       (예: "대표종목 쏠림 vs 고른 상승"의 차이를 등락률 격차로 판단).
     - "N종목 중 M개 동방향" 같은 기계적 수치·비율 자체는 AI가 판단 근거로만
       참고하고 본문 문장에 그대로 옮겨 적지 말 것.
     - ⚠️ 표(#### [당일 주도 섹터 및 테마])의 '핵심 흐름 한 줄' 칸도 위와 동일하게
       적용된다 — [업종폭]·판정 라벨 문구(예: "구성종목 N% 이상 하락하며 업종 전반
       약세")를 표현만 살짝 바꿔 그대로 옮기지 말 것. 여러 날에 걸쳐 셀 문장 골격이
       똑같이 반복되는 문제가 실제 발생했다. 행마다 그 섹터의 대표종목명·등락률
       격차·[대표종목 뉴스] 등 구체적 근거로 표현을 다르게 쓸 것(예: "OO전자 홀로
       급등 견인" vs "구성종목 고르게 상승").
   - 공통 금지 사항:
     - 테마명·섹터명 임의 생성 금지 (예: "호남 반도체 테마주", "AI 수혜주" 등 데이터에 없는 표현 금지)
     - 기관명·단체명·정책명 임의 생성 금지. 뉴스 헤드라인에 없는 기관명 절대 금지.
     - "상한가" 표현은 데이터 블록에 [상한가] 태그가 붙은 종목에만 사용. 태그 없으면 "급등", "강세" 표현.
     - 시황·지수 전체 흐름 헤드라인을 개별 종목 이유로 사용 금지.
     - 수급 방향 표현 일치: 하락 종목에 "수급 유입", "매수 유입" 표현 금지.
     - ⚠️ 목표가·투자의견(예: "목표가 OOO원 제시", "매수 의견 유지") 서술 절대 금지 —
       위 뉴스 헤드라인 데이터에 증권사명과 목표가 수치가 함께 명시된 경우가 아니면
       목표가 자체를 언급하지 말 것. 언급 시 반드시 "OO증권 목표가 OOO원"처럼
       증권사명을 함께 표기 — 증권사명 없이 목표가 수치만 쓰는 것 절대 금지.
     - ⚠️ 공시·계약·수주 등 구체적 사건(예: "OOO억 규모 수주 공시", "2분기 호실적 전망")은
       뉴스 헤드라인 데이터에 해당 사건이 실제로 있을 때만 서술. 등락률 수치만 있고
       사건 내용이 없는 종목은 재료를 추측해서 채우지 말 것 — 그런 종목은 이유 서술
       없이 종목명과 등락률만 표기.
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

[아래 "📌 오늘 시장 핵심" 섹션 작성 지침 — 이 지침 설명 텍스트 자체는 절대 본문에
출력하지 말 것. 실제로 출력할 것은 오직 "📌 **오늘 시장 핵심**" 다음에 이어지는
요약 문장뿐이다.]
- 이 섹션은 구글 검색 결과 설명(meta description)으로 그대로 노출된다.
- 날짜·코스피·코스닥 등락률·핵심 종목/섹터 키워드를 첫 2문장 안에 반드시 포함.
- 이모티콘 제외 150자 이내로 압축.
- 첫 문장은 "코스피는~", "오늘 증시는~"으로 시작 금지. 날짜와 함께, 오늘 데이터에서
  가장 눈에 띄는 것 1가지(최대 등락 섹터·상한가 종목·특징주 급등락 등)를 구체적
  수치와 함께 배치할 것. 지수 종합 수치는 두 번째 문장부터.
- 데이터 블록에 없는 내용 금지.

실제 출력 형식 (아래 줄만 그대로 따라 출력 — 괄호 설명·지침 문구는 출력 금지):
📌 **오늘 시장 핵심** KOSPI·KOSDAQ 수치 포함 2~3문장 요약.

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
- **[종목A]** <span style="color:#e74c3c"><b>+X.XX%</b></span> — [관련뉴스 있으면 명사형 구로 압축 요약 — 없으면 대시 포함 생략]
- **[종목B]** <span style="color:#e74c3c"><b>+X.XX%</b></span>

#### 📉 하락 특징주
- **[종목X]** <span style="color:#3182f6"><b>-X.XX%</b></span> — [명사형 구 요약 — 없으면 대시 포함 생략]
- **[종목Y]** <span style="color:#3182f6"><b>-X.XX%</b></span>

#### 📰 뉴스 기반 특징주
(데이터 블록 '뉴스기반 특징주'에 있는 종목만 작성. 없으면 이 섹션 전체 생략.)
- **[종목명]** <span style="color:#e74c3c"><b>+X.XX%</b></span> — [해당 종목 [뉴스] 내용에서만 추출한 명사형 구 — "~습니다" 종결 금지]

---

### 🔮 3. 다음 거래일 전망 ({next_day_label})

오늘 섹터·특징주 흐름을 근거로 2~3문장. 과도한 낙관·비관 금지.
데이터에 없는 매크로("고금리 환경" 등) 단정 금지. 불확실성은 "~가능성이 있습니다" 어조 사용
(단, "~가능성이 있습니다"로 2문장 연속 종결 금지).
마지막 문장은 {next_day_label}에 확인할 체크포인트 1가지(오늘 주도 섹터의 지속 여부,
특정 지수선 유지 여부 등 오늘 데이터에서 도출되는 것)를 관찰형으로 제시할 것.
⚠️ 문단 골격을 매번 똑같이 반복하지 말 것 — 첫 문장 시작 방식을 회차마다 바꿀 것
(예: 주도 섹터명으로 시작 / 지수 레벨로 시작 / 리스크 요인으로 시작 등을 번갈아 사용).
체크포인트 문장의 표현도 매번 다르게 쓸 것("~인지 지켜볼 필요가 있습니다",
"~여부가 관건입니다", "~에 주목할 필요가 있습니다" 등을 돌아가며 사용 — 동일 어구 반복 금지).
'내일' 대신 반드시 '{next_day_label}' 표현 사용.

---

출력 형식 — 아래 3줄 헤더 뒤에 마크다운 본문만 작성 (면책 조항은 포함하지 말 것. 시스템이 자동 추가):
TITLE: 핵심내용만 (날짜 prefix 없이 핵심내용만 출력 — 예: "반도체 강세로 KOSPI 상승, 전자장비·바이오주 주도")
  - 핵심내용은 오늘 지수 등락률·상위 섹터명·대장 종목명만 사용. 임의 조어·축약어·한자 조합 절대 금지.
  - HTML 태그 없는 순수 텍스트. 대괄호 [] 사용 금지.
CONTENT:
[마크다운 본문]"""

    prompt += _build_retry_feedback(prev_issues)
    return prompt


def _strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def _strip_code_fences(text: str) -> str:
    """AI 응답에 마크다운 코드펜스(```html 등)가 섞여 TITLE에 그대로 박제되는
    사고 방지용 — 6/25 발행 글 제목에 코드펜스가 섞여 저장된 뒤 Blogger '인기
    게시물' 위젯에 계속 노출된 사례 확인 후 추가."""
    return re.sub(r"```[a-zA-Z]*", "", text).strip()


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
            raw_title = _strip_code_fences(raw_title)
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


def generate_post(data: dict, model: str = "claude-sonnet-4-6", prev_issues: list = None) -> dict:
    prompt = _build_prompt(data, prev_issues=prev_issues)
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
