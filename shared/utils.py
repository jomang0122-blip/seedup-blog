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
