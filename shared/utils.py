# -*- coding: utf-8 -*-
import re
import time


def extract_text(message) -> str:
    """Anthropic 메시지 응답에서 텍스트 블록만 골라 이어붙인다.

    확장 사고(thinking) 모드에서는 content[0]이 텍스트가 아니라
    ThinkingBlock으로 먼저 오는 경우가 있어, content[0].text로
    무조건 첫 블록을 가정하면 AttributeError가 난다(2026-08-07 us_daily
    발행 실패 실사고). type이 "text"인 블록만 골라 이어붙여 방어한다."""
    return "".join(block.text for block in message.content if block.type == "text")


def fetch_with_retry(url: str, *, retries: int = 3, backoff: float = 2.0, **kwargs):
    """requests.get with exponential backoff retry (네트워크 불안정 대응)."""
    import requests
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last_exc


NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://finance.naver.com/",
}


def fetch_naver_market_listing(market: str):
    """네이버 모바일 API로 시장 전종목 등락률·시가총액 수집 (KRX 직접 호출 회피).

    2026-08-26 kr_daily 실사고: fdr.StockListing()이 내부적으로 data.krx.co.kr을
    직접 호출하는데, GitHub Actions 러너 IP를 KRX가 간헐적으로 차단해 발행이
    중단됐다(pykrx가 같은 이유로 이미 폐기된 것과 동일 계열 문제 — 어느 러너가
    배정되느냐에 따라 무작위로 걸리므로 재시도해도 같은 작업 안에서는 IP가
    바뀌지 않아 소용없다). 이미 지수 조회에 쓰고 있는 네이버 모바일 API로
    전종목 목록도 통일해 KRX 의존을 제거한다. kr_daily에서 신설해 kr_weekly의
    같은 계열 실사고(2026-08-29, get_top_stocks_weekly 데이터 공백 → 발행 중단)
    이후 두 job이 공유하도록 shared로 옮겼다.

    반환 컬럼은 fdr.StockListing()과 동일하게 맞춰(Name/Code/ChagesRatio/
    Marcap/Amount/Volume) 호출하는 쪽 로직을 바꾸지 않아도 되게 한다.
    """
    import pandas as pd

    rows = []
    page = 1
    while True:
        resp = fetch_with_retry(
            f"https://m.stock.naver.com/api/stocks/marketValue/{market}",
            params={"page": page, "pageSize": 100},
            headers=NAVER_HEADERS, timeout=10,
        )
        data = resp.json()
        stocks = data.get("stocks", [])
        if not stocks:
            break
        for s in stocks:
            if s.get("stockEndType") != "stock":
                continue
            try:
                rows.append({
                    "Name": s["stockName"],
                    "Code": s["itemCode"],
                    "ChagesRatio": float(s["fluctuationsRatio"]),
                    "Marcap": float(s["marketValueRaw"]),
                    "Amount": float(s.get("accumulatedTradingValueRaw", 0) or 0),
                    "Volume": float(s.get("accumulatedTradingVolumeRaw", 0) or 0),
                })
            except (KeyError, ValueError, TypeError):
                continue
        if page * 100 >= data.get("totalCount", 0):
            break
        page += 1
        time.sleep(0.2)
    return pd.DataFrame(rows)


_NAVER_INDEX_PAGE_SIZE = 60   # pageSize 100 이상은 HTTP 400 (실측, 2026-09-10)
_NAVER_AMOUNT_MAX_PAGES = 40  # 페이지당 6행 — 폭주 방지 상한


def fetch_naver_index_history(index: str, days: int = 30) -> list:
    """네이버 모바일 API로 지수 일별 종가·등락률 조회 (FDR 지수 의존 제거).

    2026-09-10 실사고: FDR의 지수 데이터(KS11·KQ11)가 2026-09-08부터 갱신을
    멈췄다(개별 종목은 정상 — 지수 경로만 고장). FDR 0.9.202가 이미 PyPI
    최신이라 버전을 올려 고칠 수도 없고, 한국 IP에서도 동일해 KRX 차단 같은
    지역 문제도 아니다. kr_daily는 이 때문에 발행 날짜가 09-07에 고착돼
    9월 8일·9일 리포트가 둘 다 "9월 7일"로 나갔고, kr_weekly는 주간 일별
    등락률 표가 통째로 틀어질 상황이었다.

    fetch_naver_market_listing()이 전종목 목록에서 KRX 의존을 걷어낸 것과
    같은 처방을 지수에 적용한다. 등락률은 우리가 계산하지 않고 네이버가 준
    값을 그대로 쓴다 — 종가와 등락률이 한 행에 묶여 있어 어긋날 수 없다.

    Args:
        index: "KOSPI" 또는 "KOSDAQ"
        days:  가져올 거래일 수. 60을 넘으면 페이지를 나눠 이어붙인다
               (pageSize 100 이상은 네이버가 HTTP 400으로 거절 — 실측 확인).
    Returns:
        과거→최신 순 [{"date": "YYYY-MM-DD", "close": float, "change_pct": float}]
    """
    out, page = [], 1
    while len(out) < days:
        resp = fetch_with_retry(
            f"https://m.stock.naver.com/api/index/{index}/price",
            params={"pageSize": _NAVER_INDEX_PAGE_SIZE, "page": page},
            headers=NAVER_HEADERS, timeout=10,
        )
        rows = resp.json()
        if not rows:
            break
        for r in rows:
            try:
                out.append({
                    "date":       r["localTradedAt"],
                    "close":      float(str(r["closePrice"]).replace(",", "")),
                    "change_pct": float(str(r["fluctuationsRatio"]).replace(",", "")),
                })
            except (KeyError, ValueError, TypeError):
                continue
        if len(rows) < _NAVER_INDEX_PAGE_SIZE:
            break                              # 마지막 페이지
        page += 1
        time.sleep(0.2)
    out.sort(key=lambda x: x["date"])          # 네이버는 최신순 → 과거순으로 뒤집는다
    return out[-days:] if len(out) > days else out


def fetch_naver_index_amount(index: str, days: int = 45) -> dict:
    """지수 일별 거래대금 — {"YYYY-MM-DD": 원 단위 float}

    ⚠️ 단위 주의: 네이버 표는 **백만원** 단위로 표시하는데, 이 함수는 **원**으로
    환산해 반환한다. 교체 이전 FDR의 Amount 컬럼이 원 단위였고 kr_monthly의
    ai_writer가 `avg_amount / 1e12`로 조원을 만들기 때문 — 백만원을 그대로
    돌려주면 거래대금이 100만분의 1로 표시된다.

    지수 시세 JSON API(fetch_naver_index_history)는 시가·고가·저가·종가와
    등락률만 주고 거래대금이 없다. 월간 결산의 "일평균 거래대금(전월 대비)"은
    총괄이 2026-09-01에 직접 요청해 넣은 지표라 뺄 수 없어, 거래대금만
    네이버 금융의 일별 지수 표(HTML)에서 따로 가져온다.

    종가·등락률까지 여기서 같이 받지 않는 이유: 데일리·위클리가 이미 JSON
    API로 검증돼 있는데 월간만 다른 경로를 쓰면 또 출처가 갈라진다. 거래대금은
    날짜를 키로 병합하므로 이번 사고처럼 "위치가 어긋나 값이 뒤바뀌는" 위험은
    없다.

    Args:
        index: "KOSPI" 또는 "KOSDAQ"
        days:  가져올 거래일 수 (페이지당 6행)
    """
    import re

    out = {}
    page = 1
    while len(out) < days and page <= _NAVER_AMOUNT_MAX_PAGES:
        resp = fetch_with_retry(
            "https://finance.naver.com/sise/sise_index_day.naver",
            params={"code": index, "page": page},
            headers=NAVER_HEADERS, timeout=10,
        )
        resp.encoding = "euc-kr"
        found = 0
        for tr in re.findall(r"<tr>(.*?)</tr>", resp.text, re.S):
            tds = [re.sub(r"<[^>]+>", "", t).strip()
                   for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            tds = [t for t in tds if t]
            if len(tds) < 6 or not re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", tds[0]):
                continue                       # 페이지 이동 링크 행 등은 건너뛴다
            try:
                # tds = [날짜, 체결가, 전일비, 등락률, 거래량(천주), 거래대금(백만원)]
                out[tds[0].replace(".", "-")] = float(tds[5].replace(",", "")) * 1e6
                found += 1
            except ValueError:
                continue
        if not found:
            break
        page += 1
        time.sleep(0.2)
    return out


def fetch_naver_fx_history(days: int = 45, code: str = "FX_USDKRW") -> list:
    """원달러 등 환율 일별 종가·등락률 (FDR 환율 지연 대응).

    2026-09-10 확인: FDR의 USD/KRW가 2거래일 밀려 있었다(지수처럼 완전히
    멈추지는 않았지만, 월말에 도는 월간 결산에서 마지막 날 환율이 빠질 수 있다).
    지수와 같은 처방으로 네이버에서 직접 받는다 — 응답 필드 구조도 동일하다.

    Returns:
        과거→최신 순 [{"date": "YYYY-MM-DD", "close": float, "change_pct": float}]
    """
    resp = fetch_with_retry(
        "https://m.stock.naver.com/front-api/marketIndex/prices",
        params={"category": "exchange", "reutersCode": code,
                "page": 1, "pageSize": days},
        headers=NAVER_HEADERS, timeout=10,
    )
    out = []
    for r in resp.json().get("result", []):
        try:
            out.append({
                "date":       r["localTradedAt"],
                "close":      float(str(r["closePrice"]).replace(",", "")),
                "change_pct": float(str(r["fluctuationsRatio"]).replace(",", "")),
            })
        except (KeyError, ValueError, TypeError):
            continue
    out.sort(key=lambda x: x["date"])
    return out


_WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]

_KANJI_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def find_kanji(text: str) -> list:
    """본문에 섞인 한자(CJK 한자 블록) 문자 목록 반환. 비어 있으면 정상.

    AI가 한국어 생성 중 같은 음의 한자 토큰을 섞는 사고 차단용
    (실사례: 발행 글에 株主·利益 노출, 2026-07-05 발견). 발행 게이트에서
    검출되면 재생성으로 처리한다.
    """
    return _KANJI_RE.findall(text or "")


def fix_weekday_labels(text: str, ref_date: str) -> str:
    """본문의 'M월 D일(요일)' 패턴에서 잘못된 요일을 실제 요일로 자동 교정.

    AI가 달력 지침을 무시하고 요일을 지어내는 환각 차단용 (B025 원칙).
    ref_date: 'YYYY-MM-DD' — 연도 판정 기준. 11~12월 리포트에서 1~2월 언급 시 다음 해로 처리.
    """
    from datetime import datetime as _dt
    try:
        ref = _dt.strptime(ref_date, "%Y-%m-%d")
    except Exception:
        return text

    def _repl(m):
        month, day = int(m.group(1)), int(m.group(2))
        suffix = m.group(4) or ""
        year = ref.year + 1 if (ref.month >= 11 and month <= 2) else ref.year
        try:
            correct = _WEEKDAYS_KR[_dt(year, month, day).weekday()]
        except ValueError:
            return m.group(0)
        return f"{month}월 {day}일({correct}{suffix})"

    return re.sub(r"(\d{1,2})월\s*(\d{1,2})일\s*\(([월화수목금토일])(요일)?\)", _repl, text)


def us_time_rule_block(ref_date: str) -> str:
    """미국 동부시간(ET)↔한국시간(KST) 변환 규칙 블록 — 프롬프트 주입용.

    서머타임 여부를 Python이 판정해 시차를 명시 (AI 직접 계산 금지).
    """
    import pytz
    from datetime import datetime as _dt
    try:
        d = _dt.strptime(ref_date, "%Y-%m-%d")
        eastern = pytz.timezone("America/New_York")
        is_dst = bool(eastern.localize(d.replace(hour=12)).dst())
    except Exception:
        is_dst = True
    offset = 13 if is_dst else 14
    name = "서머타임(EDT)" if is_dst else "표준시(EST)"
    ex1 = 8 + offset - 12   # 동부 오전 8:30 → KST 오후
    ex2 = (16 + offset) - 24  # 동부 오후 4시(마감) → KST 다음날 오전
    return (
        f"현재 미국 동부는 {name} 적용 중 — 한국시간 = 동부시간 + {offset}시간\n"
        f"변환 예시 (이 시차로만 계산, 직접 계산 절대 금지):\n"
        f"  동부 오전 8시 30분 = 한국시간 오후 {ex1}시 30분\n"
        f"  동부 오후 4시(정규장 마감) = 한국시간 다음날 오전 {ex2}시"
    )


def next_kr_trading_day_label(date_str: str) -> str:
    """다음 국내 증시 개장일 레이블 ('7월 6일(월)') — 주말·공휴일·근로자의날·연말휴장 건너뜀.

    AI가 '내일'을 임의로 쓰다가 휴장일(주말 다음날 등)을 가리키는 환각 차단용 (B025 원칙).
    """
    from datetime import datetime as _dt, timedelta
    try:
        d = _dt.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return ""
    try:
        import holidays as _hol
        kr = _hol.KR(years=[d.year, d.year + 1])
    except Exception:
        kr = {}
    nd = d + timedelta(days=1)
    while nd.weekday() >= 5 or nd in kr or (nd.month, nd.day) in [(5, 1), (12, 31)]:
        nd += timedelta(days=1)
    return f"{nd.month}월 {nd.day}일({_WEEKDAYS_KR[nd.weekday()]})"


# 문장 종결부호 뒤에 숫자가 바로 이어지면(예: "-14.02%") 소수점이지 문장 끝이
# 아니다 — truncate_at_sentence()가 "-14."을 문장 끝으로 오판해 자르는 사고
# 방지용(2026-07-29 kr_daily 재발 실사고: 등락률 소수점에서 잘림).
_SENTENCE_END_RE = re.compile(r"[.!?](?!\d)")


def truncate_at_sentence(text: str, max_len: int) -> str:
    """max_len을 넘으면 그 안에서 마지막 '문장 종결' 부호 뒤까지만 남기고 자른다.
    숫자 뒤 소수점(-14.02%)은 문장 끝으로 오인하지 않는다. 적당한 문장부호가
    없으면(문장이 통째로 너무 길면) 원래대로 글자 수 컷 폴백.
    검색설명(SEARCH_DESC)이 130자 제한에 걸려 문장 중간에서 뚝 끊기는 사고
    방지용(2026-07-29 kr_daily 실사고: "...실적 부진으로 두"에서 잘림)."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    matches = list(_SENTENCE_END_RE.finditer(truncated))
    if matches and matches[-1].end() >= max_len // 2:
        return truncated[:matches[-1].end()]
    return truncated.rstrip()


def fmt_amount(amount: int, force_eok: bool = False) -> str:
    """순매수거래대금(원) → 조원(1조↑) 또는 억원 단위 문자열 (kr_daily·kr_weekly 공통).
    force_eok=True 이면 크기 무관하게 억원 단위 강제.
    """
    val_eok = amount // 100_000_000
    sign = "+" if amount >= 0 else "-"
    if not force_eok and abs(val_eok) >= 10_000:
        val_jo = abs(val_eok) / 10_000
        return f"{sign}{val_jo:.1f}조원"
    return f"{sign}{abs(val_eok):,}억"


KR_REPORT_LINKS_HTML = (
    '<div style="margin-top:24px;padding:16px;background:#f2f4f6;border-radius:8px;">'
    '<p style="margin:0 0 8px;font-weight:bold;font-size:13px;">📎 국내증시 리포트 모아보기</p>'
    '<p style="margin:4px 0;font-size:13px;">👉 <a href="https://www.seedup-invest.com/search/label/%EA%B5%AD%EB%82%B4%EB%8D%B0%EC%9D%BC%EB%A6%AC">국내증시 데일리 리포트 모아보기</a></p>'
    '<p style="margin:4px 0;font-size:13px;">👉 <a href="https://www.seedup-invest.com/search/label/%EA%B5%AD%EB%82%B4%EC%9C%84%ED%81%B4%EB%A6%AC">국내증시 위클리 리포트 모아보기</a></p>'
    '</div>'
)

US_REPORT_LINKS_HTML = (
    '<div style="margin-top:24px;padding:16px;background:#f2f4f6;border-radius:8px;">'
    '<p style="margin:0 0 8px;font-weight:bold;font-size:13px;">📎 미국증시 리포트 모아보기</p>'
    '<p style="margin:4px 0;font-size:13px;">👉 <a href="https://www.seedup-invest.com/search/label/%EB%AF%B8%EA%B5%AD%EB%8D%B0%EC%9D%BC%EB%A6%AC">미국증시 데일리 리포트 모아보기</a></p>'
    '<p style="margin:4px 0;font-size:13px;">👉 <a href="https://www.seedup-invest.com/search/label/%EB%AF%B8%EA%B5%AD%EC%9C%84%ED%81%B4%EB%A6%AC">미국증시 위클리 리포트 모아보기</a></p>'
    '</div>'
)

DISCLAIMER = (
    '<p style="margin-top:30px;padding:15px;background:#f5f5f5;'
    'border-left:4px solid #999;font-size:12px;color:#666;">'
    '⚠️ 본 포스팅은 공시 데이터 및 시장 뉴스를 바탕으로 작성된 단순 정보 제공 목적의 글이며, '
    '특정 종목에 대한 매수 또는 매도 추천이 아닙니다. '
    '모든 투자에 대한 판단과 책임은 투자자 본인에게 있습니다. '
    'SeedUP 블로그는 본 내용으로 인한 손실에 대해 책임을 지지 않습니다. ⚠️</p>'
)


def apply_color_spans(html: str) -> str:
    """HTML 내 등락률 수치에 부호 기준으로 색상 span 태그를 강제 적용.

    AI가 스스로 색상 태그를 붙여도 부호와 색상이 어긋날 수 있어
    (예: +0.19%를 파란색으로 잘못 감싸는 경우), 기존 색상 태그가 있어도
    무시하고 부호만 보고 색상을 다시 정한다 (한국 증권 관례: 상승=빨강, 하락=파랑).
    """
    placeholders = {}
    _idx = [0]

    def _recolor_and_protect(m):
        val = m.group(1)
        color = "#e74c3c" if val.startswith("+") else "#3182f6"
        key = f"__P{_idx[0]}__"
        _idx[0] += 1
        placeholders[key] = f'<span style="color:{color}"><b>{val}</b></span>'
        return key

    # 이미 색상 span으로 감싸진 수치 — 색상 무시하고 부호 기준 재작성 후 보호
    # (보호하지 않으면 아래 2차 정규식이 방금 고친 span을 또 감싸는 이중 중첩 버그 발생)
    # <b> 유무 모두 매칭 — AI가 마크다운 **볼드** 안에 span을 직접 써서 md_to_html이
    # <strong><span>+X%</span></strong>로 변환하는 경우(<b> 없음)도 실제 발견됨(2026-07-07)
    html = re.sub(
        r'<span style="color:#(?:e74c3c|3182f6)">(?:<b>)?([+-]\d+\.\d+%)(?:</b>)?</span>',
        _recolor_and_protect, html
    )
    # 미처리 수치(색상 태그 없는 +/-X.XX%)에도 부호 기준 색상 적용 — 숫자·따옴표 뒤는 제외
    html = re.sub(
        r'(?<!["\d])([+-]\d+\.\d+%)',
        lambda m: f'<span style="color:{"#e74c3c" if m.group(1).startswith("+") else "#3182f6"}"><b>{m.group(1)}</b></span>',
        html
    )
    for key, val in placeholders.items():
        html = html.replace(key, val)
    return html


def md_to_html(text: str) -> str:
    """마크다운 → HTML 변환 + 테이블 인라인 스타일 주입.
    모든 job(kr_daily, us_daily, kr_weekly, us_weekly)이 공유하는 공통 함수.
    """
    try:
        import re
        import markdown as md
        from bs4 import BeautifulSoup
        # ### 헤딩을 Python markdown 라이브러리에 의존하지 않고 직접 HTML로 변환
        # (라이브러리는 앞에 빈 줄이 없으면 ### 를 그대로 출력하는 버그 있음)
        # SEO: 프롬프트의 ###/####를 h2/h3로 한 단계 승격 — 글 최상위 소제목이
        # h3부터 시작하면 문서 구조상 h2가 비어 검색엔진 구조 파악에 불리 (2026-07-06)
        def _heading(m):
            level = max(2, min(6, len(m.group(1)) - 1))
            content = m.group(2).strip()
            content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
            content = re.sub(r'\*(.+?)\*', r'\1', content)
            return f'<h{level}>{content}</h{level}>'
        text = re.sub(r'^(#{1,6})\s+(.+)$', _heading, text, flags=re.MULTILINE)
        html = md.markdown(text, extensions=["tables"])
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            table["border"] = "1"
            table["style"] = "border-collapse:collapse;width:100%;font-size:14px;"
        # 모바일 좁은 화면에서 표가 찌그러지거나 페이지 전체가 가로 스크롤되는 것을
        # 막기 위해 표만 감싸는 스크롤 컨테이너 추가 (2026-07-09)
        for table in soup.find_all("table"):
            wrapper = soup.new_tag("div", style="overflow-x:auto;")
            table.wrap(wrapper)
        # 각 행의 첫 칸(섹터명·지수명 등 라벨 컬럼)은 줄바꿈 금지 — 긴 한글 라벨이
        # 다른 칸(설명 텍스트) 길이에 밀려 2줄로 쪼개지는 가독성 저하 방지.
        # 등락률 컬럼도 같은 이유로 줄바꿈 금지 — kr_daily 라이브 발행글에서
        # "-0.46%"가 두 줄로 쪼개지는 문제가 실측 확인됨(2026-07-06). 단, 이
        # 함수는 5개 파이프라인이 공유하고 표마다 컬럼 순서가 달라(예: kr_weekly
        # "주간 주도 섹터" 표는 2번째 컬럼이 섹터명이라 고정 인덱스로 판단하면
        # 위험) 컬럼 위치가 아니라 헤더 텍스트("등락률" 포함)로 그 열 전체를
        # 찾아 nowrap을 적용한다.
        for table in soup.find_all("table"):
            header_cells = table.find("tr").find_all(["th", "td"]) if table.find("tr") else []
            nowrap_cols = {
                i for i, h in enumerate(header_cells)
                if "등락률" in h.get_text()
            }
            for row in table.find_all("tr"):
                for i, cell in enumerate(row.find_all(["th", "td"])):
                    is_header = cell.name == "th"
                    style = "padding:8px;background:#f2f4f6;text-align:left;" if is_header else "padding:8px;vertical-align:top;"
                    if i == 0 or i in nowrap_cols:
                        style += "white-space:nowrap;"
                    cell["style"] = style
        return str(soup)
    except ImportError:
        return text
