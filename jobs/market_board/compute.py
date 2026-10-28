# -*- coding: utf-8 -*-
"""시장 현황판 — 랩 지표 25개 계산 → data/board/board_lab.json (API 크레딧 0).

실행: cd auto_publisher && python jobs/market_board/compute.py [--no-save]
  - data/board/breadth_hist.csv · fg_hist.csv 에 새 날짜만 덧붙이고(--no-save면 저장 안 함)
  - 게이지 2개(한국·미국 공포탐욕) + 카드 23개를 랩 화면(var D)과 같은 모양으로 저장
항목 하나가 실패해도 나머지는 계속한다. 실패한 항목은 이전 board_lab.json 값을 그대로 두고
'실패' 목록에 남긴다(조용히 빼지 않는다). 전 종목 주가가 실패하면 시장 폭·한국 공포탐욕만 이전 값.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect as C       # noqa: E402
import indicators as I    # noqa: E402

DATA = HERE.parent.parent / "data" / "board"
OUT = DATA / "board_lab.json"
PRICE_DAYS = 420          # 달력일 → 약 285거래일. 신고저 253일 + 빈 날 메우기 여유
MAX_FAIL_RATIO = 0.01     # 주가 조회 실패가 1%를 넘으면 그날 시장 폭을 계산하지 않는다

BREADTH_SPEC = [("200일선위비율", "200일선 위 종목", "%", 2), ("상승종목비율", "상승종목 비율", "%", 2),
                ("신고가마이너스신저가", "신고가 - 신저가", "개", 0), ("거래대금집중도", "거래대금 집중도", "%", 2)]
CARD_SPEC = [   # 랩 build_lab_v3.CARD_SPEC (시장PBR은 1차 제외, 2026-10-28 총괄 결정)
    ("KOSPI", "국내증시", "KOSPI", "", 2), ("KOSDAQ", "국내증시", "KOSDAQ", "", 2),
    ("원달러환율", "국내증시", "원달러 환율", "원", 2),
    ("S&P500", "해외증시", "S&P500", "", 2), ("나스닥", "해외증시", "나스닥", "", 2),
    ("VIX", "해외증시", "VIX", "", 2), ("니케이", "해외증시", "니케이225", "", 2),
    ("상해종합", "해외증시", "상해종합", "", 2),
    ("국고채3년", "금리신용", "국고채 3년", "%", 3), ("회사채AA3년", "금리신용", "회사채 AA- 3년", "%", 3),
    ("미국채10년", "금리신용", "미국채 10년", "%", 3), ("미국장단기금리차", "금리신용", "미국 10Y-2Y", "%p", 2),
    ("하이일드스프레드", "금리신용", "하이일드 스프레드", "%p", 2), ("미국기준금리", "금리신용", "미국 기준금리", "%", 2),
    ("금", "원자재위험자산", "금", "$", 2), ("WTI원유", "원자재위험자산", "WTI원유", "$", 2),
    ("구리", "원자재위험자산", "구리", "$", 2), ("비트코인", "원자재위험자산", "비트코인", "$", 1),
    ("달러인덱스", "원자재위험자산", "달러인덱스", "", 2),
]
ECOS_COL = {"국고채3년": "국고채3년", "회사채AA3년": "회사채AA_3년"}


def say(m):
    print(m, flush=True)


def read_hist(name):
    df = pd.read_csv(DATA / name, index_col="date", parse_dates=["date"])
    return df.sort_index()


def run(save=True, trim_days=0):
    """trim_days: 검증용 — 이력 마지막 N거래일을 지운 채 계산해 랩 값과 비교할 때만 쓴다.
    반환: (payload, 시장 폭 이력, 공포탐욕 이력)"""
    started = dt.datetime.now(C.KST)
    notes = json.loads((DATA / "notes.json").read_text(encoding="utf-8"))
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    fails, basis = [], {}

    # 1) 지수·환율·원자재·미국 금리 (FDR) ─────────────────────
    fdr_panel, fdr_fails = C.fetch_fdr()
    fails += [f"FDR {f['항목']}: {f['오류'][:80]}" for f in fdr_fails]
    # 국내 지수는 오늘 행을 버린다 — 10-28 실측: 장 마감 뒤 FDR KS11 오늘 값 6,007.78이 네이버 확정 종가
    # 6,012.44와 달랐다(전날까지는 일치). 지금은 네이버로 받지만, 서버는 아침에 돌므로 오늘 행은 원래 안 쓴다.
    for k in ("KOSPI", "KOSDAQ"):
        if k in fdr_panel:
            fdr_panel.loc[fdr_panel.index >= C.today_kst(), k] = float("nan")
    say(f"[1/5] FDR {fdr_panel.shape[1]}개 성공 / {len(fdr_fails)}개 실패")

    # 2) 국내 금리 (ECOS) ─────────────────────────────────
    rates = None
    key = C.ecos_key()
    if not key:
        fails.append("ECOS: 인증키 없음 (ECOS_API_KEY)")
    else:
        try:
            rates = C.fetch_ecos(key)
            say(f"[2/5] ECOS {len(rates)}일, 마지막 {rates.index[-1].date()}")
        except Exception as e:
            fails.append(f"ECOS: {str(e)[:120]}")
    # 3) CNN ─────────────────────────────────────────────
    cnn = None
    try:
        cnn = C.fetch_cnn()
        say(f"[3/5] CNN {len(cnn)}일, 마지막 {cnn.index[-1].date()} {cnn.iloc[-1]:.1f}")
    except Exception as e:
        fails.append(f"CNN: {str(e)[:120]}")

    # 4) 전 종목 주가 → 시장 폭·공포탐욕 새 날짜 ───────────────────
    bh, fh = read_hist("breadth_hist.csv"), read_hist("fg_hist.csv")
    if trim_days:
        bh, fh = bh.iloc[:-trim_days], fh.iloc[:-trim_days]
    new_b, new_f = [], []
    try:
        uni = pd.read_csv(DATA / "universe.csv", dtype=str)["ticker"].tolist()
        start = (C.today_kst() - pd.Timedelta(days=PRICE_DAYS)).strftime("%Y%m%d")
        t0 = dt.datetime.now()
        px, pfail = C.fetch_prices(uni + [C.LEV_ETF, C.INV_ETF], start)
        say(f"[4/5] 주가 {px['ticker'].nunique()}종목 받음, 실패 {len(pfail)} ({(dt.datetime.now() - t0).seconds}초)")
        if len(pfail) > MAX_FAIL_RATIO * len(uni):
            raise RuntimeError(f"주가 조회 실패 {len(pfail)}종목 > {MAX_FAIL_RATIO:.0%} — 시장 폭 계산 안 함")
        chk = C.check_two_sources(px)
        basis["두 출처 대조"] = f"{len(chk)}건 모두 0.1% 이내 (기준 3종목 vs FinanceDataReader)"
        etf = px[px["ticker"].isin([C.LEV_ETF, C.INV_ETF])]
        st = px[px["ticker"].isin(uni)]
        close = st.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index()
        volume = st.pivot_table(index="date", columns="ticker", values="volume", aggfunc="last").sort_index()
        bh_new, new_b = I.append_new(bh, I.breadth_frame(close, volume))
        if len(close) - 1 - HL_LOOKBACK_NEED() < len(new_b):
            raise RuntimeError("빠진 날이 받아 온 주가 창보다 길다 — 씨앗을 다시 만들어야 함")
        bh = bh_new
        if rates is None or "KOSPI" not in fdr_panel:
            raise RuntimeError("공포탐욕 재료(ECOS 금리·KOSPI) 없음")
        amt = lambda tk: (etf[etf.ticker == tk].set_index("date").pipe(lambda d: d["close"] * d["volume"]))
        # 랩 fear_greed_v2: 코스피는 네이버 일봉, 전 종목 확정 종가 마지막 날까지만
        kospi = fdr_panel["KOSPI"].dropna()
        kospi = kospi[kospi.index <= close.index[-1]]
        comp = I.fg_components(kospi, close, close * volume, rates, amt(C.LEV_ETF), amt(C.INV_ETF))
        comp = comp.loc[comp.index.isin(close.index)]
        raw_cols = [f"{c}_원시" for c in I.FG_ORDER]
        comp_hist = fh[raw_cols].rename(columns=lambda c: c[:-3])
        comp_all, new_f = I.append_new(comp_hist, comp)
        idx, sc = I.fg_index(comp_all)
        fh = pd.concat([idx, sc.add_suffix("_점수"), comp_all.add_suffix("_원시")], axis=1)
        fh.index.name = "date"
        last = close.index[-1]
        r = bh.loc[last] if last in bh.index else None
        if r is not None:
            basis["시장 폭 검산"] = {
                "기준일": str(last.date()),
                "200일선위비율": f"{r['_200일선위종목수']:.0f}종목 / {r['_계산가능종목수']:.0f}종목 = {r['200일선위비율']:.2f}%",
                "신고가-신저가": f"{r['_신고가종목수']:.0f}개 - {r['_신저가종목수']:.0f}개 = {r['신고가마이너스신저가']:+.0f}개",
                "상승종목비율": f"최근 20일 평균 {r['상승종목비율']:.2f}%",
                "거래대금집중도": f"상위 10종목이 전체의 {r['거래대금집중도']:.2f}%",
            }
    except Exception as e:
        fails.append(f"전 종목 주가·시장 폭: {str(e)[:160]}")
    say(f"      새로 붙은 날짜 — 시장 폭 {[str(d.date()) for d in new_b]} · 공포탐욕 {[str(d.date()) for d in new_f]}")

    # 5) 화면용 묶음 ──────────────────────────────────────
    old = {c["id"]: c for c in prev.get("cards", []) + prev.get("gauges", [])}
    gauges, cards = [], []
    kr = fh["공포탐욕지수"].dropna()
    gauges.append(I.prepare_gauge("KR", "한국 공포탐욕지수", kr, "자체 구성 7개 지표, 2016-12부터", notes.get("KR")))
    if cnn is not None:
        gauges.append(I.prepare_gauge("US", "미국 공포탐욕지수 (CNN)", cnn, "CNN 원본, 최근 1년치만 제공", notes.get("US")))
    elif "US" in old:
        gauges.append(old["US"])
    for cid, label, unit, digits in BREADTH_SPEC:
        cards.append({**I.prepare_card(cid, "시장폭", label, unit, bh[cid], digits, notes.get(cid))})
    for cid, group, label, unit, digits in CARD_SPEC:
        s = None
        if cid in ECOS_COL:
            s = rates[ECOS_COL[cid]] if rates is not None else None
        elif cid in fdr_panel:
            s = fdr_panel[cid]
        if s is not None and s.dropna().size > 1:
            cards.append(I.prepare_card(cid, group, label, unit, s, digits, notes.get(cid)))
        elif cid in old:
            cards.append(old[cid])
        else:
            fails.append(f"카드 {cid}: 자료 없음, 이전 값도 없음")

    gauges, cards = [slim(g) for g in gauges], [slim(c) for c in cards]
    all_dates = [c["dates"][-1] for c in cards + gauges]
    payload = {"meta": {"asof": max(all_dates), "oldest": min(all_dates),
                        "generated": started.strftime("%Y-%m-%d %H:%M KST"), "fails": fails, "basis": basis},
               "gauges": gauges, "cards": cards, "bands": BANDS}
    if save:
        bh.to_csv(DATA / "breadth_hist.csv")
        fh.to_csv(DATA / "fg_hist.csv")
        OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    say(f"[5/5] 게이지 {len(gauges)} · 카드 {len(cards)} · 실패 {len(fails)} · 최신 {payload['meta']['asof']} · 가장 오래됨 {payload['meta']['oldest']}")
    for f in fails:
        say(f"  실패: {f}")
    return payload, bh, fh


def slim(item, days=365):
    """1년 중 위치(p1)를 전체 이력으로 계산해 붙이고, 그래프용 값은 최근 1년만 남긴다.
    p1 = 랩 화면 sliceByDays(365) + pctlOf(지금보다 작은 값 비율) 그대로. pctile·years(장기 위치)는
    prepare_card가 전체 이력으로 이미 계산했다. 이미 줄인 항목(이전 값 재사용)은 그대로 둔다."""
    if "p1" in item:
        return item
    d, v = item["dates"], item["values"]
    cut = (pd.Timestamp(d[-1]) - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    keep = [(a, b) for a, b in zip(d, v) if a >= cut and b == b]
    w = [b for _, b in keep]
    p1 = round(sum(1 for x in w if x < w[-1]) / len(w) * 100) if len(w) >= 5 else None
    return {**item, "p1": p1, "dates": [a for a, _ in keep], "values": w}


def HL_LOOKBACK_NEED():
    return I.HL_DAYS   # 신고가-신저가가 오늘 앞 252일을 요구 — 창 안에서 계산 가능한 날 수의 하한


BANDS = [[0, 25, "극단적 공포", "#f04452"], [25, 45, "공포", "#f39c12"], [45, 55, "중립", "#8b95a1"],
         [55, 75, "탐욕", "#5b9bf7"], [75, 101, "극단적 탐욕", "#3182f6"]]

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-save", action="store_true")
    run(save=not ap.parse_args().no_save)
