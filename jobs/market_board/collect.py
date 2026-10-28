# -*- coding: utf-8 -*-
"""시장 현황판 — 외부 자료 수집 (API 크레딧 0).

퀀트 랩(05_재테크/03_퀀트투자/02_전략백테스트)과 같은 출처·같은 규칙으로 받는다.
  - 전 종목 주가: 네이버 siseJson 종목별 수정주가 일봉 (랩 update_prices_v3)
      · 오늘 날짜는 버린다 — 장 마감 뒤에도 출처마다 오늘 종가가 다르고 계속 바뀐다
        (랩 10-06 실측, 서버 10-28 실측: 16시 이후 전 종목 목록에 시간외 값이 섞임)
      · 기준 3종목을 FinanceDataReader 종목 시계열과 0.1% 안에서 대조, 어긋나면 중단
  - 지수·환율·원자재·미국 금리: FinanceDataReader (랩 collect_market_v1.FDR_CODES)
  - 국내 금리: 한국은행 ECOS 817Y002 (랩 collect_ecos_v1)
  - 미국 공포탐욕: CNN 공개 주소 (랩 collect_market_v1.collect_cnn_feargreed)
실패는 조용히 넘기지 않는다 — 호출하는 쪽이 항목별로 실패를 기록하고 이전 값을 쓴다.
"""
import ast
import datetime as dt
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

KST = dt.timezone(dt.timedelta(hours=9))

SISE_URL = ("https://api.finance.naver.com/siseJson.naver?symbol=%s&requestType=1"
            "&startTime=%s&endTime=20991231&timeframe=day")
REF_TICKERS = ["005930", "000660", "005490"]   # 삼성전자·SK하이닉스·POSCO홀딩스 (랩과 같음)
LEV_ETF, INV_ETF = "122630", "252670"           # KODEX 레버리지 / KODEX 200선물인버스2X

FDR_CODES = {   # 랩 collect_market_v1.FDR_CODES 그대로 (다우는 화면에 없어 뺐다)
    "KOSPI": "KS11", "KOSDAQ": "KQ11",
    "S&P500": "S&P500", "나스닥": "IXIC", "니케이": "N225", "상해종합": "SSEC",
    "VIX": "VIX",
    "원달러환율": "USD/KRW", "달러인덱스": "DX-Y.NYB",
    "미국채10년": "US10YT",
    "미국장단기금리차": "FRED:T10Y2Y",
    "하이일드스프레드": "FRED:BAMLH0A0HYM2",
    "미국기준금리": "FRED:DFF",
    "금": "GC=F", "WTI원유": "CL=F", "구리": "HG=F", "비트코인": "BTC/USD",
}

ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
ECOS_ITEMS = {"국고채3년": "010200000", "회사채AA_3년": "010300000"}

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
    "Accept": "application/json",
}


def today_kst() -> pd.Timestamp:
    return pd.Timestamp(dt.datetime.now(KST).date())


def _sise(ticker, start):
    err = ""
    for k in range(3):
        try:
            req = urllib.request.Request(SISE_URL % (ticker, start), headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore").strip()
            rows = ast.literal_eval(raw)[1:]
            return ticker, [(pd.Timestamp(r[0]), float(r[4]), float(r[5])) for r in rows if r[4]]
        except Exception as e:
            err = str(e)
            time.sleep(1 + k)
    return ticker, err


def fetch_prices(tickers, start, workers=8):
    """전 종목 종가·거래량 (date, ticker, close, volume). 오늘 날짜는 뺀다.
    반환: (DataFrame, 실패 종목 목록)"""
    rows, fail = [], []
    cut = today_kst()
    with ThreadPoolExecutor(workers) as ex:
        for tk, r in ex.map(lambda t: _sise(t, start), tickers):
            if isinstance(r, str):
                fail.append(tk)
                continue
            rows.extend((d, tk, c, v) for d, c, v in r if d < cut)
    df = pd.DataFrame(rows, columns=["date", "ticker", "close", "volume"])
    return df, fail


def check_two_sources(prices: pd.DataFrame, days=5):
    """기준 3종목 최근 며칠 종가를 FinanceDataReader 종목 시계열과 대조 (랩 v3 4번 규칙).
    0.1%를 넘게 어긋나거나 대조할 자료가 없으면 예외."""
    recent = sorted(prices["date"].unique())[-days:]
    chk = []
    for tk in REF_TICKERS:
        s = _second_source(tk, pd.Timestamp(recent[0]))
        nv = prices[prices["ticker"] == tk].set_index("date")["close"]
        for d in recent:
            if d in s.index and d in nv.index:
                chk.append((tk, str(pd.Timestamp(d).date()), float(nv[d]), float(s[d]),
                            abs(float(nv[d]) / float(s[d]) - 1) <= 0.001))
    bad = [c for c in chk if not c[4]]
    if bad or not chk:
        raise RuntimeError(f"두 출처 불일치 또는 대조 불가 — 계산 중단: {bad or '대조 자료 없음'}")
    return chk


def _second_source(ticker, since):
    """대조용 둘째 출처: FinanceDataReader 종목 시계열(랩과 같음). GitHub 서버에서 막히면 네이버 모바일
    일별 시세(siseJson과 다른 경로)로 대신한다 — 둘째 출처가 아예 없으면 대조 불가로 중단."""
    try:
        import FinanceDataReader as fdr
        s = fdr.DataReader(ticker, (since - pd.Timedelta(days=7)).strftime("%Y-%m-%d"))["Close"]
        if len(s):
            return s
    except Exception:
        pass
    req = urllib.request.Request(f"https://m.stock.naver.com/api/stock/{ticker}/price?pageSize=20&page=1",
                                 headers={"User-Agent": "Mozilla/5.0"})
    rows = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
    return pd.Series({pd.Timestamp(r["localTradedAt"]): float(r["closePrice"].replace(",", "")) for r in rows})


def fetch_fdr(start="2015-01-01"):
    """반환: (date 인덱스 DataFrame, 실패 목록). FRED 경유는 열 이름이 지표명이라 첫 열을 쓴다(랩 주석 그대로)."""
    import FinanceDataReader as fdr
    frames, fails = {}, []
    for name, code in FDR_CODES.items():
        try:
            df = fdr.DataReader(code, start)
            if df.empty:
                raise ValueError("빈 데이터")
            frames[name] = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        except Exception as e:
            fails.append({"항목": name, "코드": code, "오류": str(e)[:200]})
    panel = pd.DataFrame(frames).sort_index()
    panel.index = pd.to_datetime(panel.index)
    # 국내 지수는 네이버 일봉으로 통째 교체 (랩 collect_market_v2, 10-06): FDR KS11·KQ11이 09-17에 멈춘 적이
    # 있고 그날 값도 네이버 종가와 달랐다. 네이버가 실패하면 FDR 값을 그대로 두고 실패에 적는다.
    for col in ("KOSPI", "KOSDAQ"):
        try:
            s = naver_index(col, start.replace("-", ""))
            panel = panel.reindex(panel.index.union(s.index)).sort_index()
            panel[col] = s.reindex(panel.index)
        except Exception as e:
            fails.append({"항목": col, "코드": "네이버 siseJson", "오류": f"FDR 값 사용 — {str(e)[:150]}"})
    return panel, fails


def naver_index(sym, start="20150101"):
    """랩 collect_market_v2.naver_index 그대로."""
    req = urllib.request.Request(SISE_URL % (sym, start), headers={"User-Agent": "Mozilla/5.0"})
    rows = ast.literal_eval(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore").strip())[1:]
    s = pd.Series({pd.Timestamp(r[0]): float(r[4]) for r in rows}).sort_index()
    if len(s) < 100:
        raise RuntimeError(f"{sym} 행이 너무 적다 ({len(s)})")
    return s


def fetch_ecos(key, start="20160101"):
    """국고채3년·회사채AA_3년 일별 (date 인덱스). ECOS는 오류도 200으로 준다."""
    end = dt.datetime.now(KST).strftime("%Y%m%d")
    out = None
    for name, code in ECOS_ITEMS.items():
        rows, pos = [], 1
        while True:
            url = f"{ECOS_BASE}/{key}/json/kr/{pos}/{pos + 4999}/817Y002/D/{start}/{end}/{code}"
            with urllib.request.urlopen(url, timeout=60) as r:
                j = json.loads(r.read().decode("utf-8"))
            if "RESULT" in j:
                if j["RESULT"].get("CODE") == "INFO-200":
                    break
                raise RuntimeError(f"ECOS 오류 {j['RESULT'].get('CODE')}")   # 메시지에 키가 섞일 수 있어 코드만
            d = j["StatisticSearch"]
            got = d.get("row") or []
            rows.extend(got)
            pos += len(got)
            if len(got) < 5000 or pos > int(d.get("list_total_count", 0)):
                break
            time.sleep(0.2)
        s = pd.Series({pd.Timestamp(r["TIME"]): float(r["DATA_VALUE"]) for r in rows}, name=name)
        out = s.to_frame() if out is None else out.join(s, how="outer")
    return out.sort_index()


def fetch_cnn():
    """CNN 공포탐욕 최근 1년 (date 인덱스, score)."""
    req = urllib.request.Request(CNN_URL, headers=CNN_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    hist = pd.DataFrame(raw["fear_and_greed_historical"]["data"])
    hist["date"] = pd.to_datetime(hist["x"], unit="ms").dt.normalize()
    return hist.rename(columns={"y": "score"}).set_index("date")["score"].sort_index()


def ecos_key():
    """서버는 환경변수, PC는 퀀트 랩과 같은 키 파일. 값은 어디에도 출력하지 않는다."""
    k = os.environ.get("ECOS_API_KEY", "").strip()
    if k:
        return k
    # market_board → jobs → auto_publisher → 01_국내증시 → 02_구글_seedup → 08_블로그 → Claude Folder
    p = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "05_재테크",
                     "00_주식투자", "_설정", "ecos_api_key.txt")
    p = os.path.abspath(p)
    if os.path.exists(p):
        return open(p, encoding="utf-8-sig").read().strip()
    return ""
