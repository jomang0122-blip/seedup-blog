# -*- coding: utf-8 -*-
"""시장 현황판 — 매일 칸 자료 (국내 데일리 발행 직후, API 크레딧 0).

  - 지수 60거래일 : 네이버 모바일 지수 API (확정 종가)
  - 시장 내부 체력: data/kr_breadth_log.json — 국내 데일리가 같은 날 기록한 값 그대로(글과 숫자를 맞춘다)
  - 강한·약한 업종: 네이버 업종 API (국내 데일리 섹터 표와 같은 출처)
  - 시가총액 상위 10: 순서는 네이버 시가총액 목록, **가격·등락은 종목별 일봉** —
      16시 이후 전 종목 목록에는 시간외 값이 섞인다(10-28 실측: 컴투스 목록 31,500 / 확정 종가 31,600)
"""
import json
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent.parent / "data"
M = "https://m.stock.naver.com/api"


def _get(url):
    err = None
    for k in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        except Exception as e:
            err = e
            time.sleep(1 + k)
    raise err


def _num(s):
    return float(str(s).replace(",", ""))


def index_history(code, n=60):
    rows = _get(f"{M}/index/{code}/price?pageSize={n}&page=1")
    return [{"date": r["localTradedAt"], "close": _num(r["closePrice"]), "chg": _num(r["fluctuationsRatio"])}
            for r in reversed(rows)]


def sectors():
    g = _get(f"{M}/stocks/industry?page=1&pageSize=100")["groups"]
    out = [{"name": x["name"], "chg": _num(x["changeRate"]), "rise": int(x["riseCount"]),
            "fall": int(x["fallCount"]), "steady": int(x["steadyCount"]), "total": int(x["totalCount"])} for x in g]
    return sorted(out, key=lambda x: x["chg"], reverse=True)


def mcap_top(n=10, date=None):
    rows = _get(f"{M}/stocks/marketValue/KOSPI?page=1&pageSize={n}")["stocks"]
    out = []
    for s in rows:
        h = _get(f"{M}/stock/{s['itemCode']}/price?pageSize=2&page=1")
        day = next((r for r in h if date is None or r["localTradedAt"] == date), h[0])
        out.append({"name": s["stockName"], "code": s["itemCode"], "date": day["localTradedAt"],
                    "close": _num(day["closePrice"]), "chg": _num(day["fluctuationsRatio"]),
                    "mcap_jo": _num(s["marketValue"]) / 10000})   # 억원 → 조원
    return out


def collect():
    kospi, kosdaq = index_history("KOSPI"), index_history("KOSDAQ")
    asof = kospi[-1]["date"]
    log = json.loads((DATA / "kr_breadth_log.json").read_text(encoding="utf-8")) \
        if (DATA / "kr_breadth_log.json").exists() else {}
    breadth_date = max(log) if log else None
    sec = sectors()
    return {"asof": asof, "kospi": kospi, "kosdaq": kosdaq,
            "breadth": log.get(breadth_date, {}), "breadth_date": breadth_date,
            "breadth_recent": {d: log[d] for d in sorted(log)[-20:]},
            "sectors_top": sec[:5], "sectors_bottom": sec[-5:][::-1], "n_sectors": len(sec),
            "mcap": mcap_top(date=asof)}
