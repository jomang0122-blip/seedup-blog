# -*- coding: utf-8 -*-

DISCLAIMER = (
    '<p style="margin-top:30px;padding:15px;background:#f5f5f5;'
    'border-left:4px solid #999;font-size:12px;color:#666;">'
    '⚠️ 본 포스팅은 공시 데이터 및 시장 뉴스를 바탕으로 작성된 단순 정보 제공 목적의 글이며, '
    '특정 종목에 대한 매수 또는 매도 추천이 아닙니다. '
    '모든 투자에 대한 판단과 책임은 투자자 본인에게 있습니다. '
    'SeedUP 투자 블로그는 본 내용으로 인한 손실에 대해 책임을 지지 않습니다. ⚠️</p>'
)


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
