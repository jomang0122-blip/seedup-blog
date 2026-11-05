# -*- coding: utf-8 -*-
"""'시장 지표 읽는 법' 연재 그래프 — 현황판 자료(data/board)로 PNG를 만들어 본문 내장용 data URI로 돌려준다.

세션이 글을 쓸 때 로컬에서 부른다(자동발행 job 아님, API 크레딧 0).
색은 현황판과 같다: 공포탐욕 5구간(빨강 극단적 공포 → 파랑 극단적 탐욕), 선 #191f28, 배경 흰색.
기획서: 08_블로그/02_구글_seedup/06_시장지표연재/00_주제관리/20261103_연재기획서_v1.md
"""
import base64
import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(REPO, "data", "board")
BANDS = [(0, 25, "극단적 공포", "#f04452"), (25, 45, "공포", "#f39c12"), (45, 55, "중립", "#8b95a1"),
         (55, 75, "탐욕", "#5b9bf7"), (75, 100, "극단적 탐욕", "#3182f6")]
TXT, TXT2 = "#191f28", "#8b95a1"

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 10,
                     "axes.edgecolor": "#e5e8eb", "axes.labelcolor": TXT2, "xtick.color": TXT2, "ytick.color": TXT2})


def load_fg():
    d = pd.read_csv(os.path.join(DATA, "fg_hist.csv"), parse_dates=["date"]).set_index("date")
    return d.dropna(subset=["공포탐욕지수"])


def _uri(fig, save_as=None):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=144, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    if save_as:
        with open(save_as, "wb") as f:
            f.write(buf.getvalue())
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def fg_history(save_as=None):
    """한국 공포탐욕지수 전체 기록 + 5구간 배경 + 최저점·마지막 값 표시."""
    s = load_fg()["공포탐욕지수"]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    for lo, hi, _, col in BANDS:
        ax.axhspan(lo, hi, color=col, alpha=.08, lw=0)
    ax.plot(s.index, s.values, color=TXT, lw=.8)
    lo_d = s.idxmin()
    ax.scatter([lo_d], [s.min()], color="#f04452", s=18, zorder=3)
    ax.annotate(f"최저 {s.min():.1f}\n({lo_d:%Y.%m.%d})", (lo_d, s.min()), xytext=(12, 6), textcoords="offset points",
                fontsize=8.5, color="#f04452")
    ax.scatter([s.index[-1]], [s.iloc[-1]], color=TXT, s=18, zorder=3)
    ax.annotate(f"{s.index[-1]:%m/%d} {s.iloc[-1]:.1f}", (s.index[-1], s.iloc[-1]), xytext=(-48, 34),
                textcoords="offset points", fontsize=8.5, color=TXT, fontweight="bold",
                bbox=dict(boxstyle="round,pad=.25", fc="white", ec="#e5e8eb", lw=.6),
                arrowprops=dict(arrowstyle="-", color=TXT, lw=.6))
    for lo, hi, name, col in BANDS:
        ax.text(1.005, (lo + hi) / 200, name, transform=ax.transAxes, fontsize=8, color=col, va="center")
    ax.set_ylim(0, 100)
    ax.set_xlim(s.index[0], s.index[-1])
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(axis="y", color="#f2f4f6")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.set_title(f"한국 공포탐욕지수 ({s.index[0]:%Y.%m} ~ {s.index[-1]:%Y.%m.%d}, 시드업 자체 산출)", fontsize=10.5,
                 color=TXT, loc="left")
    return _uri(fig, save_as)


def _style(ax, title):
    ax.grid(axis="y", color="#f2f4f6")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.set_title(title, fontsize=10.5, color=TXT, loc="left")


def _mark(ax, x, y, text, color, xytext):
    ax.scatter([x], [y], color=color, s=18, zorder=3)
    ax.annotate(text, (x, y), xytext=xytext, textcoords="offset points", fontsize=8.5, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=.25", fc="white", ec="#e5e8eb", lw=.6),
                arrowprops=dict(arrowstyle="-", color=color, lw=.6))


def component_raw(col, unit_mul=100.0, unit="%", title="", save_as=None):
    """공포탐욕 구성 지표의 원시값 전체 기록 — 0선 위(탐욕 쪽)는 파랑, 아래(공포 쪽)는 빨강 음영 (2편~ 공용)."""
    s = load_fg()[col].dropna() * unit_mul
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.plot(s.index, s.values, color=TXT, lw=.8)
    ax.fill_between(s.index, s.values, 0, where=s.values >= 0, color="#3182f6", alpha=.12, lw=0)
    ax.fill_between(s.index, s.values, 0, where=s.values < 0, color="#f04452", alpha=.12, lw=0)
    ax.axhline(0, color=TXT2, lw=.6)
    _mark(ax, s.idxmin(), s.min(), f"최저 {s.min():+.1f}{unit} ({s.idxmin():%Y.%m.%d})", "#f04452", (14, -4))
    _mark(ax, s.idxmax(), s.max(), f"최고 {s.max():+.1f}{unit} ({s.idxmax():%Y.%m.%d})", "#3182f6", (-150, -6))
    _mark(ax, s.index[-1], s.iloc[-1], f"{s.index[-1]:%m/%d} {s.iloc[-1]:+.1f}{unit}", TXT, (-70, -30))
    ax.set_xlim(s.index[0], s.index[-1])
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    _style(ax, title or f"{col} ({s.index[0]:%Y.%m} ~ {s.index[-1]:%Y.%m.%d})")
    return _uri(fig, save_as)


def index_vs_ma(close, days=125, window=250, name="코스피", save_as=None):
    """지수와 N일 이동평균 — 최근 window거래일 (2편 주가 모멘텀)."""
    ma = close.rolling(days).mean()
    c, m = close.iloc[-window:], ma.iloc[-window:]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.plot(c.index, c.values, color=TXT, lw=1.1, label=f"{name} 종가")
    ax.plot(m.index, m.values, color="#3182f6", lw=1.3, label=f"{days}일 이동평균")
    ax.fill_between(c.index, c.values, m.values, where=c.values < m.values, color="#f04452", alpha=.12, lw=0)
    ax.fill_between(c.index, c.values, m.values, where=c.values >= m.values, color="#3182f6", alpha=.10, lw=0)
    gap = (c.iloc[-1] / m.iloc[-1] - 1) * 100
    _mark(ax, c.index[-1], c.iloc[-1], f"{c.index[-1]:%m/%d} {c.iloc[-1]:,.0f} (평균 대비 {gap:+.1f}%)", "#f04452", (-210, -22))
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y.%m"))
    _style(ax, f"{name}와 {days}일 이동평균 (최근 {window}거래일)")
    return _uri(fig, save_as)


def fg_band_share(save_as=None):
    """구간별로 머문 거래일 비율 가로 막대."""
    s = load_fg()["공포탐욕지수"]
    cut = pd.cut(s, [0, 25, 45, 55, 75, 101], right=False, labels=[b[2] for b in BANDS])
    share = cut.value_counts(normalize=True).reindex([b[2] for b in BANDS]) * 100
    cnt = cut.value_counts().reindex([b[2] for b in BANDS])
    fig, ax = plt.subplots(figsize=(8, 2.4))
    y = range(len(BANDS))[::-1]
    ax.barh(list(y), share.values, color=[b[3] for b in BANDS], height=.6)
    for yi, v, n in zip(y, share.values, cnt.values):
        ax.text(v + .6, yi, f"{v:.1f}%  ({n:,}일)", va="center", fontsize=9, color=TXT)
    ax.set_yticks(list(y))
    ax.set_yticklabels([b[2] for b in BANDS])
    ax.set_xlim(0, max(share.values) * 1.35)
    ax.set_xticks([])
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.set_title(f"구간별로 머문 거래일 비율 (전체 {len(s):,}거래일)", fontsize=10.5, color=TXT, loc="left")
    return _uri(fig, save_as)
