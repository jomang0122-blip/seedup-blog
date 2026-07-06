# -*- coding: utf-8 -*-
import re
import time


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
    html = re.sub(
        r'<span style="color:#(?:e74c3c|3182f6)"><b>([+-]\d+\.\d+%)</b></span>',
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
        # 각 행의 첫 칸(섹터명·지수명 등 라벨 컬럼)은 줄바꿈 금지 — 긴 한글 라벨이
        # 다른 칸(설명 텍스트) 길이에 밀려 2줄로 쪼개지는 가독성 저하 방지
        for row in soup.find_all("tr"):
            for i, cell in enumerate(row.find_all(["th", "td"])):
                is_header = cell.name == "th"
                style = "padding:8px;background:#f2f4f6;text-align:left;" if is_header else "padding:8px;vertical-align:top;"
                if i == 0:
                    style += "white-space:nowrap;"
                cell["style"] = style
        return str(soup)
    except ImportError:
        return text
