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


def fmt_amount(amount: int) -> str:
    """순매수거래대금(원) → +/-억 단위 문자열 (kr_daily·kr_weekly 공통)."""
    val = abs(amount) // 100_000_000
    return f"+{val:,}억" if amount >= 0 else f"-{val:,}억"


DISCLAIMER = (
    '<p style="margin-top:30px;padding:15px;background:#f5f5f5;'
    'border-left:4px solid #999;font-size:12px;color:#666;">'
    '⚠️ 본 포스팅은 공시 데이터 및 시장 뉴스를 바탕으로 작성된 단순 정보 제공 목적의 글이며, '
    '특정 종목에 대한 매수 또는 매도 추천이 아닙니다. '
    '모든 투자에 대한 판단과 책임은 투자자 본인에게 있습니다. '
    'SeedUP 블로그는 본 내용으로 인한 손실에 대해 책임을 지지 않습니다. ⚠️</p>'
)


def apply_color_spans(html: str) -> str:
    """HTML 내 미처리 등락률 수치에 색상 span 태그 자동 적용.
    이미 span으로 감싸진 수치는 건드리지 않음 (placeholder 보호).
    """
    placeholders = {}
    _idx = [0]

    def _protect(m):
        key = f"__P{_idx[0]}__"
        _idx[0] += 1
        placeholders[key] = m.group(0)
        return key

    # 기존 color span 보호 — DOTALL 없이 단순 패턴 (내용: <b>±X.XX%</b>)
    protected = re.sub(
        r'<span style="color:#(?:e74c3c|3182f6)"><b>[^<]+</b></span>',
        _protect, html
    )
    # 미처리 +X.XX% → 빨강(상승)
    protected = re.sub(
        r'(\+\d+\.\d+%)',
        r'<span style="color:#e74c3c"><b>\1</b></span>',
        protected
    )
    # 미처리 -X.XX% → 파랑(하락) — 숫자·따옴표 뒤는 제외
    protected = re.sub(
        r'(?<!["\d])(-\d+\.\d+%)',
        r'<span style="color:#3182f6"><b>\1</b></span>',
        protected
    )
    for key, val in placeholders.items():
        protected = protected.replace(key, val)
    return protected


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
        def _heading(m):
            level = len(m.group(1))
            return f'<h{level}>{m.group(2).strip()}</h{level}>'
        text = re.sub(r'^(#{1,6})\s+(.+)$', _heading, text, flags=re.MULTILINE)
        html = md.markdown(text, extensions=["tables"])
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            table["border"] = "1"
            table["style"] = "border-collapse:collapse;width:100%;font-size:14px;"
        for th in soup.find_all("th"):
            th["style"] = "padding:8px;background:#f2f4f6;text-align:left;"
        for td in soup.find_all("td"):
            td["style"] = "padding:8px;vertical-align:top;"
        return str(soup)
    except ImportError:
        return text
