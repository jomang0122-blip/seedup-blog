# -*- coding: utf-8 -*-
"""시장 현황판 — 네이버 하루치 시세가 랩 씨앗 주가와 맞는지 대조 (API 크레딧 0).

실행: cd auto_publisher && python tools/test_board_snapshot.py
  1) 종목 목록: 씨앗(랩) 종목 중 네이버 목록에 있는 비율, 네이버에만 있는 종목 수
  2) 가격: 네이버 '전일 종가'(오늘 종가 - 전일 대비)가 씨앗 마지막 날 종가와 같은 비율
     — 다르면 액면분할·병합 등으로 랩 주가가 수정주가로 바뀐 종목이다
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

SEED = Path(__file__).resolve().parent / "_out" / "seed_window.parquet"   # board_seed_export.py가 만듦 (저장소에 안 올림)


def fetch_listing(market):
    rows, page = [], 1
    while True:
        url = f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=100"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        for s in d.get("stocks", []):
            rows.append({"ticker": s["itemCode"], "name": s["stockName"], "type": s.get("stockEndType"),
                         "market": market,
                         "close": float(s["closePrice"].replace(",", "")),
                         "diff": float(s["compareToPreviousClosePrice"].replace(",", "")),
                         "volume": float(s.get("accumulatedTradingVolumeRaw") or 0),
                         "traded_at": s.get("localTradedAt", "")[:10]})
        if not d.get("stocks") or page * 100 >= d.get("totalCount", 0):
            break
        page += 1
        time.sleep(0.2)
    return rows


nv = pd.DataFrame(fetch_listing("KOSPI") + fetch_listing("KOSDAQ"))
nv["prev_close"] = nv["close"] - nv["diff"]
print(f"네이버 목록 {len(nv)}개 (종류별 {nv['type'].value_counts().to_dict()}), 기준 {nv['traded_at'].mode()[0]}")

seed = pd.read_parquet(SEED)
last = seed["date"].max()
sl = seed[seed["date"] == last].dropna(subset=["close"]).set_index("ticker")
print(f"씨앗 마지막 날 {pd.Timestamp(last).date()} 종목 {len(sl)}개")

st = set(sl.index)
nt = set(nv["ticker"])
print(f"\n[1] 종목 목록")
print(f"  씨앗 종목 중 네이버에 있음 {len(st & nt)} / {len(st)} = {len(st & nt) / len(st) * 100:.1f}%")
only_nv = nv[~nv["ticker"].isin(st)]
print(f"  네이버에만 있음 {len(only_nv)}개, 종류별 {only_nv['type'].value_counts().to_dict()}")
print(f"    예: {only_nv.head(12)[['ticker', 'name', 'type']].values.tolist()}")
only_seed = sorted(st - nt)
print(f"  씨앗에만 있음 {len(only_seed)}개 예: {only_seed[:10]}")

m = nv.set_index("ticker").join(sl[["close"]].rename(columns={"close": "seed_close"}), how="inner")
m["ratio"] = m["prev_close"] / m["seed_close"]
eq = (m["ratio"] - 1).abs() < 1e-6
print(f"\n[2] 가격 (네이버 전일 종가 vs 씨앗 마지막 날 종가)")
print(f"  일치 {int(eq.sum())} / {len(m)} = {eq.mean() * 100:.2f}%")
bad = m[~eq].sort_values("ratio")
print(f"  불일치 {len(bad)}개 (비율 = 네이버 / 씨앗)")
print(bad[["name", "type", "prev_close", "seed_close", "ratio"]].head(15).to_string())
