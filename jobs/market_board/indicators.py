# -*- coding: utf-8 -*-
"""시장 현황판 — 지표 계산 (API 크레딧 0).

계산식은 퀀트 랩 코드를 **그대로 옮겼다** (서버에 랩 코드가 없어서). 고칠 때는 랩 원본과
같이 고칠 것 — 두 곳이 어긋나면 현황판과 랩 화면 숫자가 달라진다.
  시장 폭     : 02_전략백테스트/breadth_v1.py  _pct_above_ma · _pct_advancing · _high_low · _amount_concentration
  공포탐욕    : 02_전략백테스트/fear_greed_v1.py  build_components · rolling_percentile · build_index · label
  카드·게이지 : 02_전략백테스트/report_dashboard_v2.py  prepare_card · prepare_gauge · percentile_of_last · peak_stats
  변화량      : 02_전략백테스트/build_lab_v3.py  _deltas

이력 갱신 원칙: 이미 있는 날짜는 건드리지 않고 **기록에 없는 새 날짜만** 덧붙인다
(랩이 맞게 계산해 둔 과거 값을 서버 값으로 바꾸지 않기 위해). 서버가 며칠 쉬어도
받아 온 주가 창 안이면 빠진 날이 다음 실행에서 함께 채워진다.
"""
import numpy as np
import pandas as pd

# ── breadth_v1.py ─────────────────────────────────────
MA_DAYS, HL_DAYS, ADV_SMOOTH, TOP_N, MIN_STOCKS = 200, 252, 20, 10, 300


def _pct_above_ma(close, days=MA_DAYS):
    ma = close.rolling(days, min_periods=days).mean()
    valid = close.notna() & ma.notna()
    above = (close > ma) & valid
    n_valid = valid.sum(axis=1)
    n_above = above.sum(axis=1)
    return n_above / n_valid.replace(0, np.nan) * 100.0, n_above, n_valid


def _pct_advancing(close, smooth=ADV_SMOOTH):
    chg = close.diff()
    valid = chg.notna()
    up = (chg > 0) & valid
    raw = up.sum(axis=1) / valid.sum(axis=1).replace(0, np.nan) * 100.0
    return raw.rolling(smooth, min_periods=max(1, min(smooth, smooth // 2))).mean(), raw


def _high_low(close, days=HL_DAYS):
    prev = close.shift(1)
    hi = prev.rolling(days, min_periods=days).max()
    lo = prev.rolling(days, min_periods=days).min()
    valid = close.notna() & hi.notna()
    n_hi = ((close > hi) & valid).sum(axis=1)
    n_lo = ((close < lo) & valid).sum(axis=1)
    return (n_hi - n_lo), n_hi, n_lo


def _amount_concentration(close, volume, top_n=TOP_N):
    amt = close * volume
    tot = amt.sum(axis=1)
    arr = np.nan_to_num(amt.to_numpy(dtype="float64"), nan=0.0)
    if arr.shape[1] <= top_n:
        topsum = arr.sum(axis=1)
    else:
        topsum = np.partition(arr, -top_n, axis=1)[:, -top_n:].sum(axis=1)
    top_s = pd.Series(topsum, index=amt.index)
    return top_s / tot.replace(0, np.nan) * 100.0, top_s, tot


def breadth_frame(close, volume):
    """breadth_v1.compute의 df 부분 (시총가중 격차는 1차 제외)."""
    pct_ma, n_above, n_valid = _pct_above_ma(close)
    pct_adv, _ = _pct_advancing(close)
    hl, n_hi, n_lo = _high_low(close)
    conc, _, _ = _amount_concentration(close, volume)
    df = pd.DataFrame({
        "200일선위비율": pct_ma, "상승종목비율": pct_adv,
        "신고가마이너스신저가": hl.astype(float), "거래대금집중도": conc,
        "_계산가능종목수": n_valid.astype(float), "_200일선위종목수": n_above.astype(float),
        "_신고가종목수": n_hi.astype(float), "_신저가종목수": n_lo.astype(float),
    })
    return df[df["_계산가능종목수"] >= MIN_STOCKS]


# ── fear_greed_v1.py ──────────────────────────────────
FG_MIN_OBS, FG_WINDOW, KTB3Y_DURATION = 250, 750, 2.8
FG_INVERT = {"변동성", "신용스프레드", "하락베팅수요"}
FG_ORDER = ["주가모멘텀", "주가강도", "주가폭", "변동성", "안전자산수요", "신용스프레드", "하락베팅수요"]


def rolling_percentile(s, window=FG_WINDOW, min_obs=FG_MIN_OBS):
    def _pr(a):
        cur = a[-1]
        if np.isnan(cur):
            return np.nan
        v = a[~np.isnan(a)]
        if len(v) < min_obs:
            return np.nan
        return float((v < cur).mean() * 100.0)
    return s.rolling(window, min_periods=min_obs).apply(_pr, raw=True)


def fg_components(kospi, close, amount, rates, lev_amt, inv_amt):
    out = {}
    out["주가모멘텀"] = kospi / kospi.rolling(125).mean() - 1.0
    hi = close.rolling(250, min_periods=200).max()
    lo = close.rolling(250, min_periods=200).min()
    nh = (close >= hi * 0.999).sum(axis=1)
    nl = (close <= lo * 1.001).sum(axis=1)
    out["주가강도"] = (nh / (nh + nl)).replace([np.inf, -np.inf], np.nan)
    chg = close.diff()
    up = amount.where(chg > 0).sum(axis=1)
    dn = amount.where(chg < 0).sum(axis=1)
    out["주가폭"] = (up / (up + dn)).replace([np.inf, -np.inf], np.nan)
    out["변동성"] = kospi.pct_change().rolling(20).std() * np.sqrt(252)
    y = rates["국고채3년"].reindex(kospi.index).ffill() / 100.0
    bond_ret = y * (20.0 / 252.0) - KTB3Y_DURATION * (y - y.shift(20))
    out["안전자산수요"] = (kospi / kospi.shift(20) - 1.0) - bond_ret
    out["신용스프레드"] = (rates["회사채AA_3년"] - rates["국고채3년"]).reindex(kospi.index).ffill()
    li, ii = lev_amt.reindex(kospi.index), inv_amt.reindex(kospi.index)
    out["하락베팅수요"] = (ii / (li + ii)).replace([np.inf, -np.inf], np.nan)
    return pd.DataFrame(out)[FG_ORDER]


def fg_index(components):
    scores = {}
    for c in components.columns:
        p = rolling_percentile(components[c])
        scores[c] = (100.0 - p) if c in FG_INVERT else p
    sc = pd.DataFrame(scores)[list(components.columns)]
    n_ok = sc.notna().sum(axis=1)
    return sc.mean(axis=1, skipna=True).where(n_ok >= 4).rename("공포탐욕지수"), sc


def fg_label(v):
    if pd.isna(v):
        return "-"
    if v < 25:
        return "극단적 공포"
    if v < 45:
        return "공포"
    if v <= 55:
        return "중립"
    if v <= 75:
        return "탐욕"
    return "극단적 탐욕"


# ── report_dashboard_v2.py · build_lab_v3.py ───────────
def _dates(idx):
    return [f"{d.year:04d}-{d.month:02d}-{d.day:02d}" for d in idx]


def percentile_of_last(values):
    v = [x for x in values if x == x]
    if len(v) < 30:
        return None
    cur = v[-1]
    return round(sum(1 for x in v if x < cur) / len(v) * 100.0, 1)


def peak_stats(values, dates=None):
    v = [x for x in values if x == x]
    if len(v) < 2:
        return None
    cur, mx, mn = v[-1], max(v), min(v)
    out = {"max": mx, "min": mn, "from_peak": ((cur / mx - 1.0) * 100.0) if mx else None}
    if dates is not None and len(dates) == len(values):
        out["max_date"] = max(((x, d) for x, d in zip(values, dates) if x == x), key=lambda t: t[0])[1]
    return out


def prepare_card(id_, group, label, unit, s, digits=2, desc=None):
    s = s.dropna()
    vals = [float(v) for v in s.values]
    dates = _dates(s.index)
    last, prev = vals[-1], (vals[-2] if len(vals) > 1 else None)
    chg = ((last / prev - 1.0) * 100.0) if prev else None
    return {"id": id_, "group": group, "label": label, "unit": unit,
            "value": round(last, digits), "chg_pct": round(chg, 2) if chg is not None else None,
            "pctile": percentile_of_last(vals), "years": round(len(vals) / 252.0, 1),
            "peak": peak_stats(vals, dates), "desc": desc,
            "dates": dates, "values": [round(v, digits) for v in vals]}


def deltas(s):
    s = s.dropna()
    if len(s) < 2:
        return {}
    cur, last = float(s.iloc[-1]), s.index[-1]
    out = {}
    for lab, days in [("전일", 1), ("1주전", 7), ("1개월전", 30), ("1년전", 365)]:
        past = s.loc[s.index <= last - pd.Timedelta(days=days)]
        if len(past):
            out[lab] = cur - float(past.iloc[-1])
    return out


def prepare_gauge(id_, label, s, note="", desc=None):
    s = s.dropna()
    vals = [float(v) for v in s.values]
    return {"id": id_, "label": label, "value": round(vals[-1], 1), "rating": fg_label(vals[-1]),
            "deltas": {k: round(v, 1) for k, v in deltas(s).items()},
            "dates": _dates(s.index), "values": [round(v, 2) for v in vals], "note": note, "desc": desc,
            "pctile": percentile_of_last(vals), "years": round(len(vals) / 252.0, 1), "unit": ""}


# ── 이력에 새 날짜만 덧붙이기 ─────────────────────────────
def append_new(hist: pd.DataFrame, fresh: pd.DataFrame):
    """hist에 없는 날짜의 fresh 행만 붙인다. 반환: (합친 표, 새로 붙은 날짜 목록)"""
    new = fresh.loc[fresh.index > hist.index.max()].dropna(how="all")
    if new.empty:
        return hist, []
    return pd.concat([hist, new[hist.columns.intersection(new.columns)]]).sort_index(), list(new.index)
