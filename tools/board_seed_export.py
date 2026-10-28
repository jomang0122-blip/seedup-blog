# -*- coding: utf-8 -*-
"""시장 현황판 씨앗 자료 내보내기 — PC 전용, 1회 실행 (API 크레딧 0).

서버(GitHub Actions)는 퀀트 랩의 10년치 원본 주가를 갖고 있지 않다. 서버는 실행할 때마다
최근 약 285거래일 주가를 네이버에서 새로 받아 최근 20거래일 지표만 다시 계산하고, 그 앞의
10년 이력은 여기서 내보낸 랩 계산 결과를 이어 쓴다(2026-10-28 Step 3 설계).

실행: cd auto_publisher && python tools/board_seed_export.py
출력: data/board/ (저장소에 올림, CSV — 서버에 parquet 라이브러리가 없고 한 줄씩 늘 때 git 차이가 작다)
  universe.csv         계산 대상 종목 = 랩 주가표에서 최근 90일 안에 시세가 있는 종목
  breadth_hist.csv     시장 폭 4종 일별 이력 (랩 breadth.parquet 그대로)
  fg_hist.csv          한국 공포탐욕 지수·7개 점수·7개 원시값 일별 이력
  notes.json           카드 설명 문구 (랩 화면 desc 그대로)
  _seed_근거.json      기준일·건수·재현 검사 결과
      tools/_out/ (저장소에 안 올림, 서버 계산을 랩과 대조할 때만 씀)
  seed_window.parquet  최근 WINDOW거래일 전 종목 종가·거래량

재현 검사: 잘라낸 씨앗만으로 마지막 날 시장 폭 4종과 공포탐욕 구성요소 3종(전 종목 주가로
계산하는 것)을 다시 계산해 랩 값과 같은지 확인한다. 다르면 예외 — 씨앗이 모자라다는 뜻이다.
"""
import io
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(r"G:\내 드라이브\Claude Folder\05_재테크\03_퀀트투자\02_전략백테스트")
sys.path.insert(0, str(LAB))
OUT = Path(__file__).resolve().parent.parent / "data" / "board"
UNIVERSE_DAYS = 90   # 상승종목비율이 20거래일 평균이라, 그 사이 상장폐지된 종목도 넣어야 랩과 같다 (16일로는 0.01%p 어긋남, 10-28 실측)
WINDOW = 280   # 신고저 252일(+오늘 제외 1일)·200일선·공포탐욕 250일을 모두 덮는 길이

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

import backtest_v6          # noqa: E402
import breadth_v1 as BR     # noqa: E402
import factors_v1 as F      # noqa: E402
import fear_greed_v1 as FG  # noqa: E402
import fear_greed_v2 as FG2  # noqa: E402  랩 화면이 실제로 쓰는 판(10-07부터, 코스피=네이버·확정 종가 날짜까지)

OUT.mkdir(parents=True, exist_ok=True)
print("랩 주가표 적재 중 (구글 드라이브라 수 분 걸릴 수 있음)")
bt = backtest_v6.Backtest(initial_cash=100_000_000)
pp = F.Panel(bt)
close, volume = bt.close, pp.volume
print(f"  전체 {close.shape[0]}일 x {close.shape[1]}종목, 마지막 {close.index[-1].date()}")

# ── 1) 씨앗 주가 ───────────────────────────────────────
c_w, v_w = close.tail(WINDOW), volume.reindex(close.index).tail(WINDOW)
long = (pd.concat({"close": c_w.stack(), "volume": v_w.stack()}, axis=1)
        .reset_index().rename(columns={"level_0": "date", "level_1": "ticker"}))
long.columns = ["date", "ticker", "close", "volume"]
long["close"] = long["close"].astype("float64")
long["volume"] = long["volume"].astype("float64")
LOCAL = OUT.parent.parent / "tools" / "_out"
LOCAL.mkdir(parents=True, exist_ok=True)
long.to_parquet(LOCAL / "seed_window.parquet", index=False, compression="zstd")

last_seen = close.apply(lambda s: s.last_valid_index())
active = sorted(t for t, d in last_seen.items() if d is not None and d >= close.index[-1] - pd.Timedelta(days=UNIVERSE_DAYS))
pd.DataFrame({"ticker": active}).to_csv(OUT / "universe.csv", index=False)
print(f"  계산 대상 종목 {len(active)}개 (최근 {UNIVERSE_DAYS}일 안에 시세 있음)")

# ── 2) 시장 폭 이력 ────────────────────────────────────
bdf = BR.load()
if isinstance(bdf, tuple):   # (시장 폭, 시총가중 격차)
    bdf = bdf[0]
bdf.index.name = "date"
bdf.to_csv(OUT / "breadth_hist.csv")

# ── 2-1) 카드 설명 문구: 랩 화면에 실제로 박힌 desc를 그대로 ─────
_s = (LAB.parent / "05_리포트" / "2_시장_v1.html").read_text(encoding="utf-8")
_i = _s.find("var D = ")
_D = json.loads(_s[_i + 8:_s.find("\n", _i)].rstrip().rstrip(";"))
notes = {c["id"]: c.get("desc") for c in _D["cards"] + _D["gauges"]}
io.open(OUT / "notes.json", "w", encoding="utf-8").write(json.dumps(notes, ensure_ascii=False, indent=1))

# ── 3) 공포탐욕 이력 ───────────────────────────────────
print("공포탐욕 재계산 (FinanceDataReader로 KOSPI·ETF 조회)")
idx, sc, comp, fg_basis = FG2.load_all(bt=bt)
fg = pd.concat([idx, sc.add_suffix("_점수"), comp.add_suffix("_원시")], axis=1)
fg.index.name = "date"
fg.to_csv(OUT / "fg_hist.csv")

# ── 4) 재현 검사: 씨앗만으로 마지막 날 값이 같은가 ──────────
last = close.index[-1]
checks = {}


def same(name, mine, lab, tol=1e-9):
    ok = (pd.isna(mine) and pd.isna(lab)) or abs(float(mine) - float(lab)) <= tol
    checks[name] = {"씨앗으로 계산": None if pd.isna(mine) else round(float(mine), 6),
                    "랩 값": None if pd.isna(lab) else round(float(lab), 6), "일치": bool(ok)}


pma, _, _ = BR._pct_above_ma(c_w)
padv, _ = BR._pct_advancing(c_w)
hl, _, _ = BR._high_low(c_w)
conc, _, _ = BR._amount_concentration(c_w, v_w)
lab_b = bdf.loc[last] if last in bdf.index else None
if lab_b is None:
    raise RuntimeError(f"랩 시장 폭 이력에 마지막 주가일 {last.date()}이 없다 - 랩을 다시 돌릴 것")
same("200일선위비율", pma.iloc[-1], lab_b["200일선위비율"])
same("상승종목비율", padv.iloc[-1], lab_b["상승종목비율"])
same("신고가마이너스신저가", hl.iloc[-1], lab_b["신고가마이너스신저가"])
same("거래대금집중도", conc.iloc[-1], lab_b["거래대금집중도"])

# 공포탐욕 중 전 종목 주가로 계산하는 2종(주가강도·주가폭) — 나머지는 지수·금리·ETF라 씨앗과 무관
kospi_dummy = pd.Series(1.0, index=c_w.index)
rates_dummy = pd.DataFrame({"국고채3년": 3.0, "회사채AA_3년": 3.5}, index=c_w.index)
etf_dummy = pd.Series(1.0, index=c_w.index)
comp_w = FG.build_components(kospi_dummy, c_w, c_w * v_w, rates_dummy, etf_dummy, etf_dummy)
for k in ("주가강도", "주가폭"):
    same(f"공포탐욕_{k}", comp_w[k].iloc[-1], comp.loc[last, k])

basis = {
    "만든 날": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
    "씨앗 주가": {"시작": str(c_w.index[0].date()), "끝": str(last.date()),
               "거래일": int(len(c_w)), "종목": int(c_w.shape[1]),
               "출처": "퀀트 랩 backtest_v6.Backtest.close / factors_v1.Panel.volume"},
    "시장 폭 이력": {"행": int(len(bdf)), "마지막": str(bdf.index[-1].date())},
    "공포탐욕 이력": {"행": int(len(fg)), "지수 마지막": str(idx.dropna().index[-1].date()),
                 "지수 마지막 값": round(float(idx.dropna().iloc[-1]), 2), "근거": fg_basis},
    "재현 검사": checks,
}
io.open(OUT / "_seed_근거.json", "w", encoding="utf-8").write(
    json.dumps(basis, ensure_ascii=False, indent=2, default=str))

for f in sorted(OUT.iterdir()):
    print(f"  {f.name:24s} {f.stat().st_size / 1024:8.0f} KB")
print("\n재현 검사 (씨앗만으로 마지막 날 계산 vs 랩)")
for k, v in checks.items():
    print(f"  {'OK' if v['일치'] else 'NG'}  {k:22s} 씨앗 {v['씨앗으로 계산']}  랩 {v['랩 값']}")
bad = [k for k, v in checks.items() if not v["일치"]]
if bad:
    raise SystemExit(f"재현 실패 {bad} - WINDOW를 늘리거나 계산 범위를 확인할 것")
print("\n모두 일치")
