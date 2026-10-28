# -*- coding: utf-8 -*-
"""시장 현황판 서버 계산 — 랩 값과 1:1 대조 (API 크레딧 0, 파일 저장 없음).

실행: cd auto_publisher && python tools/test_board_compute.py
방법: 이력(랩이 계산한 값)에서 마지막 TRIM거래일을 지운 채 서버 계산을 돌려, 서버가 새로
      채운 날짜들의 값을 지우기 전 랩 값과 비교한다. 카드 23개는 랩 화면(2_시장_v1.html)의
      마지막 값과 비교한다.
"""
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "jobs" / "market_board"))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import compute  # noqa: E402

TRIM = 5
LAB_HTML = Path(r"G:\내 드라이브\Claude Folder\05_재테크\03_퀀트투자\05_리포트\2_시장_v1.html")
results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"  {'OK ' if ok else 'NG '} {label}" + (f" — {detail}" if detail else ""))


lab_b, lab_f = compute.read_hist("breadth_hist.csv"), compute.read_hist("fg_hist.csv")
payload, bh, fh = compute.run(save=False, trim_days=TRIM)
days = lab_b.index[-TRIM:]

print(f"\n[1] 시장 폭 — 지운 {TRIM}거래일을 서버가 다시 계산 ({days[0].date()} 부터 {days[-1].date()} 까지)")
for col in ["200일선위비율", "상승종목비율", "신고가마이너스신저가", "거래대금집중도"]:
    diffs = [(d.date(), lab_b.at[d, col], bh.at[d, col] if d in bh.index else None) for d in days]
    worst = max(abs(a - b) if b is not None else 1e9 for _, a, b in diffs)
    check(f"{col}", worst < 1e-6, f"최대 차이 {worst:.2e} · 마지막 날 랩 {diffs[-1][1]:.4f} / 서버 {diffs[-1][2]}")

print(f"\n[2] 한국 공포탐욕 — 같은 {TRIM}거래일")
for col in ["공포탐욕지수"] + [f"{c}_원시" for c in compute.I.FG_ORDER]:
    diffs = [(lab_f.at[d, col], fh.at[d, col] if d in fh.index else None) for d in days if d in lab_f.index]
    worst = max(abs(a - b) if (b is not None and a == a and b == b) else (0 if a != a and b != b else 1e9)
                for a, b in diffs)
    check(col, worst < 1e-6, f"최대 차이 {worst:.2e} · 마지막 랩 {diffs[-1][0]:.6f} / 서버 {diffs[-1][1]:.6f}")

print("\n[3] 카드 23개 + 게이지 2개 — 랩 화면 마지막 값과 비교")
s = LAB_HTML.read_text(encoding="utf-8")
i = s.find("var D = ")
D = json.loads(s[i + 8:s.find("\n", i)].rstrip().rstrip(";"))
lab_items = {c["id"]: c for c in D["cards"] + D["gauges"]}
for c in payload["gauges"] + payload["cards"]:
    L = lab_items.get(c["id"])
    if not L:
        check(c["id"], False, "랩 화면에 없음")
        continue
    # 둘 다 가진 날짜 중 오늘 이전의 마지막 날에서 비교 — 오늘 값은 받는 시각마다 달라서(24시간 거래 항목,
    # 장 마감 직후 지수) 같은 날 다른 시각 값끼리 비교하게 되면 계산이 맞아도 어긋난다.
    lh, sh = dict(zip(L["dates"], L["values"])), dict(zip(c["dates"], c["values"]))
    today = str(compute.C.today_kst().date())
    common = sorted(d for d in set(lh) & set(sh) if d < today)
    if not common:
        check(c["id"], False, "겹치는 날짜 없음")
        continue
    d = common[-1]
    ok = abs(float(lh[d]) - float(sh[d])) < 1e-6
    check(f"{c['id']:14s} {d}", ok, f"랩 {lh[d]} / 서버 {sh[d]} (마지막 날 랩 {L['dates'][-1]} · 서버 {c['dates'][-1]})")

print(f"\n실패 항목: {payload['meta']['fails'] or '없음'}")
print(f"검산: {json.dumps(payload['meta']['basis'], ensure_ascii=False, indent=1)}")
bad = results.count(False)
print(f"\n총 {len(results)}건 / 불일치 {bad}건")
sys.exit(1 if bad else 0)
