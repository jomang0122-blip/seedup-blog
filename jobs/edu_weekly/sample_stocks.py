# -*- coding: utf-8 -*-
"""
시드업 클래스 예시 차트용 "기본 종목" 우선순위 목록.

본문에 실존 기업이 이미 근거를 갖고 언급된 경우가 아니라면(예: 뉴스 인용 사례),
차트 하나면 되는 개념 설명(캔들·이동평균선·호가창 등)에는 이 목록에서 종목을
순서대로 배정한다 — 총괄이 "대중이 이해하기 쉽고 검색도 많은" 종목 위주로
가자고 확정한 방침(2026-08-18)에 따라, 시가총액 상위 종목을 우선 사용하고
매번 삼성전자로만 몰리지 않도록 글 번호에 따라 순환 배정한다.

출처: FinanceDataReader KRX 시가총액 상위(우선주 제외) 실데이터 조회, 2026-08-18 기준.
시가총액 순위는 시간이 지나며 바뀌므로, 주기적으로 아래 명령으로 재확인해서 갱신할 것:

    import FinanceDataReader as fdr
    df = fdr.StockListing('KRX')
    df[df['Market'].isin(['KOSPI','KOSDAQ'])].sort_values('Marcap', ascending=False).head(20)
"""

SAMPLE_STOCKS = [
    "삼성전자",
    "SK하이닉스",
    "현대차",
    "삼성전기",
    "LG에너지솔루션",
    "삼성바이오로직스",
    "삼성생명",
    "삼성물산",
    "KB금융",
    "한화에어로스페이스",
    "기아",
    "HD현대중공업",
    "신한지주",
    "현대모비스",
    "셀트리온",
]


def assign_sample_stock(topic_id: int) -> str:
    """topic_id를 기준으로 목록을 순환 배정 — 항상 같은 id는 항상 같은 종목을 받는다."""
    return SAMPLE_STOCKS[(topic_id - 1) % len(SAMPLE_STOCKS)]
