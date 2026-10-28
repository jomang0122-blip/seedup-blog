# -*- coding: utf-8 -*-
"""진단: 서버가 받은 주가(네이버 siseJson) vs 랩 주가(씨앗) 종목·날짜별 대조 (크레딧 0, 저장 없음)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "jobs" / "market_board"))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import collect as C  # noqa: E402

seed = pd.read_parquet(REPO / "tools" / "_out" / "seed_window.parquet")
uni = pd.read_csv(REPO / "data" / "board" / "universe.csv", dtype=str)["ticker"].tolist()
start = (C.today_kst() - pd.Timedelta(days=420)).strftime("%Y%m%d")
px, fail = C.fetch_prices(uni, start)
L = seed.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
S = px.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
dates = L.index.intersection(S.index)
tick = L.columns.intersection(S.columns)
L, S = L.loc[dates, tick], S.loc[dates, tick]
print(f"겹치는 기간 {dates[0].date()} 부터 {dates[-1].date()} 까지 {len(dates)}일 · 종목 {len(tick)}")

both = L.notna() & S.notna()
only_l = L.notna() & S.isna()
only_s = S.notna() & L.isna()
eq = both & (np.abs(L / S - 1) < 1e-9)
print(f"둘 다 값 있음 {int(both.values.sum()):,}칸 중 같음 {int(eq.values.sum()):,} ({eq.values.sum() / both.values.sum() * 100:.3f}%)")
print(f"랩에만 값 {int(only_l.values.sum()):,}칸 · 서버에만 값 {int(only_s.values.sum()):,}칸")

neq = (both & ~eq).sum()
bad_t = neq[neq > 0].sort_values(ascending=False)
print(f"\n값이 다른 칸이 있는 종목 {len(bad_t)}개")
for t in bad_t.index[:12]:
    r = (S[t] / L[t]).dropna()
    diff = r[np.abs(r - 1) > 1e-9]
    print(f"  {t}  다른 날 {len(diff)}일 · {diff.index[0].date()} 부터 {diff.index[-1].date()} 까지 · "
          f"서버/랩 비율 {diff.min():.4f} 에서 {diff.max():.4f} · 그 뒤 같아진 날 {r.index[-1].date()} 비율 {r.iloc[-1]:.4f}")

os_t = only_s.sum()
os_t = os_t[os_t > 0].sort_values(ascending=False)
print(f"\n서버에만 값이 있는 종목 {len(os_t)}개 (랩에는 그 날 행이 없음)")
for t in os_t.index[:8]:
    d = only_s[t][only_s[t]].index
    print(f"  {t}  {len(d)}일 · 예 {[str(x.date()) for x in d[:4]]} · 서버 값 {S.loc[d[:3], t].tolist()} · 거래량 "
          f"{px[(px.ticker == t) & px.date.isin(d[:3])]['volume'].tolist()}")
ol_t = only_l.sum()
ol_t = ol_t[ol_t > 0].sort_values(ascending=False)
print(f"\n랩에만 값이 있는 종목 {len(ol_t)}개")
for t in ol_t.index[:8]:
    d = only_l[t][only_l[t]].index
    print(f"  {t}  {len(d)}일 · 예 {[str(x.date()) for x in d[:4]]}")
