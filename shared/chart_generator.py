# -*- coding: utf-8 -*-
"""
차트 이미지 생성 — 지수 캔들차트를 PNG로 렌더링해 base64 data URI로 반환.

Blogger에는 이미지 업로드 API가 마땅치 않고 레포도 비공개라 외부 URL을 못 쓰므로,
이미지를 base64로 인코딩해 <img src="data:image/png;base64,..."> 형태로 본문 HTML에
직접 삽입한다(새 인증·호스팅 불필요).

matplotlib은 한글 폰트가 기본 미탑재라 GitHub Actions에서 한글이 깨질 수 있으므로,
차트 안 텍스트(제목·축)는 영문/숫자만 사용한다. 한글 설명은 alt 속성과 포스트
본문 텍스트에서 처리한다.

1단계 범위: 지수(코스피/코스닥) 차트만 생성 — 개별 종목은 종목 추천으로 오인될
법적 리스크가 있어 이후 익명화 방안이 확정된 뒤 확대한다.
"""
import base64
import io
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import matplotlib
matplotlib.use("Agg")
import mplfinance as mpf

_INDEX_LABELS = {
    "KS11": "KOSPI",
    "KQ11": "KOSDAQ",
}

# 한국 증권 관례 색상(상승 빨강 #e74c3c, 하락 파랑 #3182f6) — B009 규칙과 통일
_MARKET_COLORS = mpf.make_marketcolors(
    up="#e74c3c", down="#3182f6", edge="inherit", wick="inherit", volume="inherit"
)
_STYLE = mpf.make_mpf_style(
    marketcolors=_MARKET_COLORS, gridstyle=":", gridcolor="#e5e8eb", facecolor="white"
)


def _fetch_ohlc(index_code: str, days: int):
    end = datetime.today()
    start = end - timedelta(days=int(days * 1.6))  # 주말·휴장 감안 여유
    df = fdr.DataReader(index_code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).tail(days)
    if df.empty:
        raise RuntimeError(f"{index_code} 캔들차트용 데이터를 가져오지 못했습니다.")
    return df


def generate_index_candle_chart(index_code: str = "KS11", days: int = 60) -> str:
    """지수 캔들차트를 base64 PNG data URI 문자열로 생성해 반환.

    index_code: FDR 지수 코드 (KS11=코스피, KQ11=코스닥)
    days: 최근 며칠치 봉을 그릴지
    """
    label = _INDEX_LABELS.get(index_code, index_code)
    df = _fetch_ohlc(index_code, days)

    buf = io.BytesIO()
    mpf.plot(
        df,
        type="candle",
        style=_STYLE,
        title=f"{label} - last {len(df)} sessions",
        ylabel="",
        volume=False,
        figsize=(9, 5),
        savefig=dict(fname=buf, format="png", dpi=110, bbox_inches="tight"),
    )
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("ascii")
    buf.close()
    return f"data:image/png;base64,{encoded}"


def chart_image_html(index_code: str = "KS11", days: int = 60, alt: str = "") -> str:
    """포스트 본문에 바로 삽입 가능한 <img> 태그 HTML을 반환.
    생성 실패 시 빈 문자열을 반환하므로, 호출부는 실패해도 발행 자체가
    막히지 않도록 반드시 반환값이 빈 문자열인지 확인해야 한다.
    """
    try:
        data_uri = generate_index_candle_chart(index_code, days)
    except Exception as e:
        print(f"  [경고] 차트 생성 실패({index_code}): {e}")
        return ""

    label = _INDEX_LABELS.get(index_code, index_code)
    alt_text = alt or f"{label} 캔들차트 (교육 목적 예시, 투자 권유 아님)"
    return (
        '<p style="text-align:center;">'
        f'<img src="{data_uri}" alt="{alt_text}" '
        'style="max-width:100%;height:auto;border:1px solid #e5e8eb;border-radius:8px;" />'
        "</p>"
    )
