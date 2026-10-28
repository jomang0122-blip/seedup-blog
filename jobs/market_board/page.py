# -*- coding: utf-8 -*-
"""시장 현황판 — 블로거 고정 페이지 HTML (시안 A v2, 2026-10-28 총괄 선택). API 크레딧 0.

입력 두 개를 합쳐 매번 페이지 전체를 다시 그린다 — 칸마다 갱신 주체가 달라도 서로 덮어쓰지 않는다.
  lab   : data/board/board_lab.json  (compute.py, 평일 다음 날 아침 · 지표 25개, 화면 표시 "다음 날 아침")
  daily : data/board/board_daily.json (daily.py, 국내 데일리 직후 · 지수·시장 내부 체력·업종·시가총액, 화면 표시 "장 마감 후")
숫자·표는 HTML 글자로 들어가 검색엔진이 읽는다. 그래프는 정적 SVG이고, 커서를 올리면 날짜·값을 띄우는
작은 스크립트만 덧붙인다(스크립트가 막혀도 그래프와 숫자는 그대로 보인다).
디자인은 CLAUDE.md 4-1(라이트, 빨강=상승·파랑=하락) · 시안 원본 03_투자도구/04_시장현황판/_작업/02_스크립트/build_board_a_v2.py
"""
import json
import math
import re
from html import escape
from urllib.parse import quote

POS, NEG = "#f04452", "#3182f6"
BLOG = "https://www.seedup-invest.com"
GROUPS = [("시장폭", "시장 폭 — 지수 뒤에 숨은 종목 전체의 체력"), ("국내증시", "국내 증시"),
          ("해외증시", "해외 증시 · 변동성"), ("금리신용", "금리 · 신용"), ("원자재위험자산", "원자재 · 위험자산")]


def rarity(p):
    if p is None:
        return "평범", "r0"
    if p <= 3 or p >= 97:
        return "매우 드묾", "r2"
    if p <= 10 or p >= 90:
        return "드묾", "r1"
    return "평범", "r0"


def fmt(v, unit=""):
    if unit == "개":
        return f"{v:,.0f}개"
    return (f"{v:,.0f}" if abs(v) >= 10000 else f"{v:,.2f}") + unit


def signed(v, unit="%"):
    if v is None:
        return '<span style="color:#8b95a1">-</span>'
    c = POS if v > 0 else NEG if v < 0 else "#8b95a1"
    return f'<span style="color:{c}">{v:+.2f}{unit}</span>'


def md(d):
    return f"{int(d[5:7])}/{int(d[8:10])}"


def band_of(v, bands):
    for lo, hi, name, col in bands:
        if lo <= v < hi:
            return name, col
    return bands[-1][2], bands[-1][3]


def meaning(desc):
    t = re.sub(r"<[^>]+>", "", (desc or {}).get("title", "")).strip()
    for sep in (" — ", " - "):
        if sep in t:
            return t.split(sep, 1)[1]
    return t


def chart(dates, values, unit="", h=36, w=300, bands=None, label=""):
    lo, hi = (0, 100) if bands else (min(values), max(values))
    rng = (hi - lo) or 1
    n = len(values)
    xs = [i / max(n - 1, 1) * 100 for i in range(n)]
    ys = [(1 - (v - lo) / rng) * 100 for v in values]
    c = "#191f28" if bands else (POS if values[-1] >= values[0] else NEG)
    line = " ".join(f"{x * w / 100:.1f},{4 + y * (h - 8) / 100:.1f}" for x, y in zip(xs, ys))
    bg = ""
    for b_lo, b_hi, _, col in (bands or []):
        y1, y2 = 4 + (1 - min(b_hi, 100) / 100) * (h - 8), 4 + (1 - b_lo / 100) * (h - 8)
        bg += f'<rect x="0" y="{y1:.1f}" width="{w}" height="{y2 - y1:.1f}" fill="{col}" opacity=".09"/>'
    data = escape(json.dumps({"d": dates, "v": values, "u": unit}, ensure_ascii=False, separators=(",", ":")))
    return (f'<div class="hv" data-s="{data}" role="img" aria-label="{escape(label)} 추이, 마지막 {dates[-1]} {fmt(values[-1], unit)}">'
            f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="height:{h}px">{bg}'
            + ("" if bands else f'<polygon points="0,{h} {line} {w},{h}" fill="{c}" opacity=".08"/>')
            + f'<polyline points="{line}" fill="none" stroke="{c}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>'
            f'<i class="end" style="left:{xs[-1]}%;top:calc(4px + {ys[-1]:.1f}% * {(h - 8) / h:.3f});background:{c}"></i>'
            f'<i class="gl"></i><i class="gd"></i><b class="tip"></b></div>')


def gauge(value, bands, size=180):
    cx, cy, r = size / 2, size / 2 + 4, size / 2 - 16

    def pt(v, rr):
        a = math.pi * (1 - v / 100)
        return cx + rr * math.cos(a), cy - rr * math.sin(a)
    arcs = ""
    for lo, hi, _, col in bands:
        (x1, y1), (x2, y2) = pt(lo, r), pt(min(hi, 100), r)
        arcs += f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 0 1 {x2:.1f},{y2:.1f}" stroke="{col}" stroke-width="13" fill="none"/>'
    nx, ny = pt(value, r - 20)
    return (f'<svg viewBox="0 0 {size} {size / 2 + 12}" width="{size}" aria-hidden="true">{arcs}'
            f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="#191f28" stroke-width="2.5" stroke-linecap="round"/>'
            f'<circle cx="{cx}" cy="{cy}" r="5" fill="#191f28"/></svg>')


def badge(kind):
    return f'<span class="bd {"bd-d" if kind == "장 마감 후" else "bd-w"}">{kind}</span>'


# ── 매일 칸 ────────────────────────────────────────────
def sec_index(d):
    out = ""
    for name, s in (("KOSPI", d["kospi"]), ("KOSDAQ", d["kosdaq"])):
        hi, lo = max(r["close"] for r in s), min(r["close"] for r in s)
        out += (f'<div class="tile"><div class="tl">{name}<span>최근 {len(s)}거래일</span></div>'
                f'<div class="tv">{s[-1]["close"]:,.2f} <small>{signed(s[-1]["chg"])}</small></div>'
                f'{chart([r["date"] for r in s], [r["close"] for r in s], "", 70, label=name)}'
                f'<div class="tn">{len(s)}일 최고 {hi:,.2f} · 최저 {lo:,.2f} · 최고점 대비 {(s[-1]["close"] / hi - 1) * 100:+.1f}%</div></div>')
    return f'<section><h3>오늘의 지수 {badge("장 마감 후")}</h3><div class="tiles">{out}</div></section>'


def breadth_sentence(b, kospi_chg):
    ups, tot = sum(m["up"] for m in b.values()), sum(m["total"] for m in b.values())
    if not tot:
        return ""
    r = ups / tot * 100
    s = ("내린 종목보다 오른 종목이 많았습니다" if r > 55 else
         "오른 종목보다 내린 종목이 많았습니다" if r < 45 else "오른 종목과 내린 종목이 비슷했습니다")
    if "KOSPI" in b and kospi_chg is not None:
        gap = kospi_chg - b["KOSPI"]["avg_chg"]
        s += (", 코스피는 지수가 평균 종목보다 강해 대형주 중심의 흐름이었습니다" if gap >= 1 else
              ", 코스피는 지수가 평균 종목보다 약해 대형주가 상대적으로 부진했습니다" if gap <= -1 else
              ", 코스피는 지수와 평균 종목의 흐름이 비슷했습니다")
    return s + "."


def sec_breadth(d):
    b = d.get("breadth") or {}
    if not b:
        return ""
    idx = {"KOSPI": d["kospi"][-1]["chg"], "KOSDAQ": d["kosdaq"][-1]["chg"]}
    rows = ""
    for name in ("KOSPI", "KOSDAQ"):
        m = b.get(name)
        if not m:
            continue
        upw, dnw = m["up"] / m["total"] * 100, m["down"] / m["total"] * 100
        rows += (f'<tr><th>{name}</th><td><div class="ud"><i style="width:{upw:.1f}%;background:{POS}"></i>'
                 f'<i style="width:{100 - upw - dnw:.1f}%;background:var(--bg3)"></i><i style="width:{dnw:.1f}%;background:{NEG}"></i></div>'
                 f'<small>{m["up"]:,} / {m["flat"]:,} / {m["down"]:,}</small></td>'
                 f'<td><b>{m["up_ratio"]:.1f}%</b></td><td>{m.get("top10_share", 0):.1f}%</td>'
                 f'<td>{signed(m["avg_chg"])} / {signed(idx[name])}</td></tr>')
    rec = d.get("breadth_recent") or {}
    trend = ""
    if len(rec) >= 5:
        ds = sorted(rec)
        tr = ""
        for name in ("KOSPI", "KOSDAQ"):
            vals = [rec[x][name]["up_ratio"] for x in ds if name in rec[x]]
            if len(vals) == len(ds):
                tr += f'<div class="tile"><div class="tl">{name} 상승 비율<span>최근 {len(ds)}거래일</span></div>{chart(ds, vals, "%", 44, label=name + " 상승 비율")}</div>'
        trend = f'<div class="tiles" style="margin-top:10px">{tr}</div>'
    note_trend = "" if trend else f" 일별 추이 그래프는 기록이 5거래일 이상 쌓이면 이 자리에 붙습니다({md(min(rec)) if rec else '10/28'} 기록 시작)."
    return (f'<section><h3>시장 내부 체력 {badge("장 마감 후")}</h3><div class="tw"><table><thead><tr><th>구분</th>'
            f'<th class="l">상승 / 보합 / 하락 종목</th><th>상승 비율</th><th>상위10 거래대금 비중</th><th>평균 종목 / 지수</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div><p class="say">{breadth_sentence(b, idx["KOSPI"])}</p>{trend}'
            f'<p class="note">보통주 기준(ETF·우선주·거래 없는 종목 제외). 평균 종목은 단순평균, 지수는 시가총액 가중입니다. '
            f'거래대금 비중은 시장별 실제 거래대금 기준이라 아래 시장 지표의 "거래대금 집중도"(두 시장 합산)와 다릅니다.{note_trend}</p></section>')


def sec_sectors(d):
    def rows(lst):
        out = ""
        for g in lst:
            t = g["total"] or 1
            out += (f'<tr><th>{escape(g["name"])}</th><td>{signed(g["chg"])}</td>'
                    f'<td><div class="ud"><i style="width:{g["rise"] / t * 100:.1f}%;background:{POS}"></i>'
                    f'<i style="width:{g["steady"] / t * 100:.1f}%;background:var(--bg3)"></i>'
                    f'<i style="width:{g["fall"] / t * 100:.1f}%;background:{NEG}"></i></div>'
                    f'<small>{g["rise"]}↑ {g["fall"]}↓ / {g["total"]}종목</small></td></tr>')
        return out
    head = '<thead><tr><th>업종</th><th>등락</th><th class="l">오른 종목 / 내린 종목</th></tr></thead>'
    return (f'<section><h3>오늘 강한 업종 · 약한 업종 {badge("장 마감 후")}</h3><div class="two">'
            f'<div class="tw"><table>{head}<tbody>{rows(d["sectors_top"])}</tbody></table></div>'
            f'<div class="tw"><table>{head}<tbody>{rows(d["sectors_bottom"])}</tbody></table></div></div>'
            f'<p class="note">네이버 증권 업종 분류 {d["n_sectors"]}개 기준. 막대는 업종 안에서 오른 종목(빨강)·보합(회색)·내린 종목(파랑) 비율입니다.</p></section>')


def sec_mcap(d):
    rows = "".join(f'<tr><td class="rk">{i}</td><th>{escape(s["name"])}</th><td>{s["close"]:,.0f}원</td>'
                   f'<td>{signed(s["chg"])}</td><td>{s["mcap_jo"]:,.1f}조</td></tr>' for i, s in enumerate(d["mcap"], 1))
    return (f'<section><h3>코스피 시가총액 상위 10 {badge("장 마감 후")}</h3><div class="tw"><table><thead><tr><th>#</th><th>종목</th>'
            f'<th>종가</th><th>등락</th><th>시가총액</th></tr></thead><tbody>{rows}</tbody></table></div>'
            f'<p class="note">지수를 실제로 움직이는 종목들입니다. 위 "평균 종목 / 지수" 차이가 크면 이 표에서 이유가 보입니다.</p></section>')


# ── 랩 칸 ──────────────────────────────────────────────
def lab_items(lab):
    return [(g["label"].replace(" (CNN)", ""), g) for g in lab["gauges"]] + [(c["label"], c) for c in lab["cards"]]


def sec_now(lab):
    items = lab_items(lab)
    high = [f'{n}({c["p1"]})' for n, c in items if c.get("p1") is not None and c["p1"] >= 90]
    low = [f'{n}({c["p1"]})' for n, c in items if c.get("p1") is not None and c["p1"] <= 10]
    li = (f'<li><b>1년 중 높은 쪽</b> {", ".join(high)}</li>' if high else "") + \
         (f'<li><b>1년 중 낮은 쪽</b> {", ".join(low)}</li>' if low else "")
    return (f'<section class="now"><h3>지금 시장은 {badge("다음 날 아침")}</h3>'
            f'<p>지표 {len(items)}개 중 <b>{len(high) + len(low)}개</b>가 최근 1년 기준으로 평소와 다른 자리에 있습니다. '
            f'괄호 숫자는 1년 중 위치(0=최저, 100=최고)이며, 좋고 나쁨이 아니라 드문 정도입니다.</p>'
            + (f"<ul>{li}</ul>" if li else "") + "</section>")


def sec_chips(lab):
    chips = "".join(f'<span class="chip {rarity(c.get("p1"))[1]}">{escape(n)} <b>{c.get("p1", "-")}</b></span>'
                    for n, c in lab_items(lab))
    return (f'<section><h3>한눈에 보기 {badge("다음 날 아침")}</h3><p class="note">숫자는 최근 1년 중 위치(0=1년 최저, 100=1년 최고). '
            f'색은 좋고 나쁨이 아니라 평소와 얼마나 다른가입니다. <span class="lg r0">평범</span> <span class="lg r1">드묾(상하위 10%)</span> '
            f'<span class="lg r2">매우 드묾(상하위 3%)</span></p><div class="chips">{chips}</div></section>')


def sec_fg(lab):
    out = ""
    for g in lab["gauges"]:
        name, col = band_of(g["value"], lab["bands"])
        dl = " · ".join(f"{k} {v:+.1f}" for k, v in g.get("deltas", {}).items())
        src = "시드업 자체 산출, 7개 지표 합성" if g["id"] == "KR" else "CNN 공개 수치"
        out += (f'<div class="fg"><div class="fgt">{escape(g["label"])}</div><div class="fgg">{gauge(g["value"], lab["bands"])}'
                f'<div class="gv" style="color:{col}">{g["value"]:.1f}</div><div class="gn" style="color:{col}">{name}</div></div>'
                f'<div class="gdl">{dl}</div>{chart(g["dates"], g["values"], "", 64, bands=lab["bands"], label=g["label"])}'
                f'<div class="tn">최근 1년 · {md(g["dates"][-1])} 기준 · 배경색은 구간(빨강 극단적 공포 → 파랑 극단적 탐욕) · {src}</div></div>')
    return f'<section><h3>공포탐욕지수 {badge("다음 날 아침")}</h3><div class="tiles">{out}</div></section>'


def sec_cards(lab):
    out = ""
    for gid, gname in GROUPS:
        body = ""
        for c in [c for c in lab["cards"] if c["group"] == gid]:
            yrs = f'{c["years"]:.0f}년' if c["years"] >= 1 else f'{c["years"]:.1f}년'
            body += (f'<div class="card"><div class="cl">{escape(c["label"])}<span class="pc {rarity(c.get("p1"))[1]}" title="최근 1년 중 위치">{c.get("p1", "-")}</span></div>'
                     f'<div class="cv">{fmt(c["value"], c["unit"])} <small>{signed(c["chg_pct"])}</small></div>'
                     f'<div class="cm">{escape(meaning(c.get("desc")))}</div>{chart(c["dates"], c["values"], c["unit"], 34, label=c["label"])}'
                     f'<div class="cf">{md(c["dates"][-1])} 기준 · 기록 {yrs} 중 {c["pctile"]:.0f}% 지점</div></div>')
        if body:
            out += f'<h4>{gname}</h4><div class="cards">{body}</div>'
    return (f'<section><h3>시장 지표 {badge("다음 날 아침")}</h3><p class="note">그래프는 최근 1년, 커서를 올리면(휴대폰은 누르면) 그날 값이 나옵니다. '
            f'오른쪽 위 숫자는 1년 중 위치, 아래 "기록 N년 중"은 쌓인 기록 전체에서의 위치입니다. 값 옆 등락은 직전 기록 대비입니다.</p>{out}</section>')


def sec_terms():
    return """<section class="terms"><h3>용어 풀이</h3><dl>
<dt>시장 폭</dt><dd>지수는 시가총액이 큰 회사 위주로 움직입니다. 시장 폭은 지수 대신 '몇 개 종목이 함께 움직였나'를 봅니다. 지수가 올라도 오른 종목이 적으면 그 상승은 좁고 약합니다.</dd>
<dt>1년 중 위치</dt><dd>최근 1년 동안 그 지표가 지금 값보다 낮았던 날의 비율입니다. 95면 1년 중 거의 가장 높은 자리, 5면 거의 가장 낮은 자리입니다.</dd>
<dt>공포탐욕지수</dt><dd>여러 시장 지표를 합쳐 투자자 심리를 0(극단적 공포)부터 100(극단적 탐욕)까지 나타낸 값입니다. 시드업 한국판은 참고용이며 매매 신호로 검증된 지표가 아닙니다.</dd>
<dt>상위10 거래대금 비중</dt><dd>그날 거래대금 상위 10종목이 시장 전체 거래대금에서 차지한 몫입니다. 높을수록 돈이 일부 종목에 몰렸습니다.</dd>
</dl></section>"""


def links(latest_daily_url=None):
    lab_url = lambda label: f"{BLOG}/search/label/{quote(label)}"
    first = (f'<a href="{escape(latest_daily_url)}">오늘의 국내 증시 시황 →</a>' if latest_daily_url
             else f'<a href="{lab_url("국내데일리")}">국내 증시 시황 →</a>')
    return (f'<nav class="lk">{first}<a href="{lab_url("국내위클리")}">주간 시황 모아보기 →</a>'
            f'<a href="{lab_url("주식투자클래스")}">시드업클래스 모아보기 →</a></nav>'
            '<p class="foot">투자 권유가 아닌 참고 자료입니다. 지수·업종·시가총액: 네이버 증권 · 시장 내부 체력: 시드업 자체 집계 · '
            '시장 지표: 시드업 인베스트먼트 랩(FinanceDataReader·한국은행 ECOS·CNN 공개 자료로 계산)</p>')


CSS = """
.sbd{--bg:#fff;--bg2:#f2f4f6;--bg3:#e5e8eb;--border:#e5e8eb;--txt:#191f28;--txt2:#8b95a1;--txt3:#b0b8c1;--pos:#f04452;--neg:#3182f6;--blue:#3182f6;
 font-family:-apple-system,'Malgun Gothic','Noto Sans KR',sans-serif;font-size:14px;color:var(--txt);background:var(--bg);line-height:1.6;font-variant-numeric:tabular-nums;container-type:inline-size}
.sbd *{box-sizing:border-box}
.sbd h2{font-size:22px;margin:0;letter-spacing:-.02em;border:0;padding:0}
.sbd h3{font-size:16px;margin:0 0 10px;display:flex;align-items:center;gap:8px;border:0;padding:0}
.sbd h4{font-size:13px;color:var(--txt2);font-weight:600;margin:18px 0 8px}
.sbd section{margin:28px 0 0}
.sbd .hd{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px solid var(--border)}
.sbd .sub{margin:4px 0 0;color:var(--txt2);font-size:13px}
.sbd .upd{font-size:12px;color:var(--txt2);display:grid;gap:2px;text-align:right}
.sbd .upd span{display:flex;align-items:center;gap:6px;justify-content:flex-end}
.sbd .dot{width:7px;height:7px;border-radius:50%;background:#20c997;display:inline-block}.sbd .dot.w{background:var(--txt3)}
.sbd .bd{font-size:11px;font-weight:600;padding:1px 7px;border-radius:6px}
.sbd .bd-d{background:#e8f3ff;color:#1b64da}.sbd .bd-w{background:var(--bg2);color:var(--txt2)}
.sbd .note{font-size:12px;color:var(--txt2);margin:8px 0 0}
.sbd .say{margin:10px 0 0;padding:10px 12px;background:var(--bg2);border-radius:8px}
.sbd .now{background:var(--bg2);border-radius:12px;padding:14px 16px;margin-top:18px}
.sbd .now p{margin:0;font-size:13px}.sbd .now ul{margin:8px 0 0;padding-left:18px;font-size:13px}.sbd .now li b{margin-right:6px}
.sbd .tw{overflow-x:auto}
.sbd table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap;border:0;margin:0}
.sbd th,.sbd td{padding:8px 10px;border:0;border-bottom:1px solid var(--border);text-align:right;background:none}
.sbd thead th{color:var(--txt2);font-weight:500;font-size:12px;background:var(--bg2)}
.sbd thead th.l{text-align:left}
.sbd tbody th{text-align:left;font-weight:600}
.sbd tbody tr:hover{background:#fafbfc}
.sbd td.rk{color:var(--txt3);width:28px}
.sbd .ud{display:flex;height:6px;border-radius:3px;overflow:hidden;min-width:120px}
.sbd .ud i{display:block;height:100%}
.sbd td small{display:block;text-align:left;color:var(--txt2);font-size:11px}
.sbd .two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.sbd .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}
.sbd .tile,.sbd .card,.sbd .fg{background:var(--bg2);border-radius:12px;padding:12px 14px;min-width:0}
.sbd .tl,.sbd .cl{font-size:12px;color:var(--txt2);display:flex;justify-content:space-between;gap:6px}
.sbd .tv{font-size:22px;font-weight:700}.sbd .tv small{font-size:13px;font-weight:600}
.sbd .tn,.sbd .cf{font-size:11px;color:var(--txt2);margin-top:4px}
.sbd .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
.sbd .cv{font-size:17px;font-weight:700}.sbd .cv small{font-size:12px;font-weight:500}
.sbd .cm{font-size:11px;color:var(--txt2);line-height:1.4;min-height:31px;margin-bottom:4px}
.sbd .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.sbd .chip{font-size:12px;padding:3px 10px;border-radius:999px;background:var(--bg2);color:var(--txt2)}
.sbd .chip b{color:var(--txt)}
.sbd .lg{font-size:11px;padding:0 6px;border-radius:6px}
.sbd .r0{background:var(--bg2);color:var(--txt2)}
.sbd .r1{background:#fff4e0 !important;color:#b9770e !important}.sbd .r2{background:#ffe6c7 !important;color:#a04f00 !important;font-weight:600}
.sbd .pc{font-size:11px;padding:0 6px;border-radius:6px;background:#fff}
.sbd .fgt{font-size:13px;font-weight:600;text-align:center}
.sbd .fgg{text-align:center}.sbd .gv{font-size:28px;font-weight:800;line-height:1.1;margin-top:2px}.sbd .gn{font-size:13px;font-weight:600}
.sbd .gdl{font-size:12px;color:var(--txt2);text-align:center;margin:6px 0 8px}
.sbd .hv{position:relative;cursor:crosshair;touch-action:pan-y}
.sbd .hv svg{display:block;width:100%;overflow:visible}
.sbd .hv i{position:absolute;pointer-events:none}
.sbd .hv .end{width:6px;height:6px;border-radius:50%;transform:translate(-50%,-50%)}
.sbd .hv .gl{top:0;bottom:0;width:1px;background:var(--txt3);display:none}
.sbd .hv .gd{width:8px;height:8px;border-radius:50%;background:var(--txt);border:2px solid #fff;transform:translate(-50%,-50%);display:none}
.sbd .hv .tip{position:absolute;bottom:calc(100% + 4px);transform:translateX(-50%);background:var(--txt);color:#fff;font-size:11px;font-weight:500;
 padding:3px 8px;border-radius:6px;white-space:nowrap;pointer-events:none;display:none;z-index:2}
.sbd .hv.on .gl,.sbd .hv.on .gd,.sbd .hv.on .tip{display:block}
.sbd .terms dl{margin:0;display:grid;gap:4px}.sbd .terms dt{font-weight:600}.sbd .terms dd{margin:0 0 8px;color:var(--txt2);font-size:13px}
.sbd .lk{display:flex;flex-wrap:wrap;gap:8px;margin-top:28px}
.sbd .lk a{font-size:13px;color:var(--blue);text-decoration:none;background:#e8f3ff;padding:6px 12px;border-radius:8px}
.sbd .foot{font-size:11px;color:var(--txt3);margin-top:14px}
@container (max-width:560px){.sbd .two{grid-template-columns:1fr}.sbd .cards{grid-template-columns:1fr 1fr}.sbd .cm{display:none}
 .sbd .tiles{grid-template-columns:1fr}.sbd .card{padding:10px}.sbd .cv{font-size:15px}}
@media (max-width:560px){.sbd .two{grid-template-columns:1fr}.sbd .cards{grid-template-columns:1fr 1fr}.sbd .cm{display:none}
 .sbd .tiles{grid-template-columns:1fr}}
"""

JS = r"""(function(){
function f(v,u){var a=Math.abs(v);var s=u==='개'?Math.round(v).toLocaleString('ko-KR'):
(a>=10000?Math.round(v).toLocaleString('ko-KR'):v.toLocaleString('ko-KR',{minimumFractionDigits:2,maximumFractionDigits:2}));return s+(u||'');}
var els=document.querySelectorAll('.sbd .hv');
for(var k=0;k<els.length;k++){(function(el){
var s=JSON.parse(el.getAttribute('data-s')),n=s.v.length,lo=Math.min.apply(null,s.v),hi=Math.max.apply(null,s.v);
if(el.querySelector('rect')){lo=0;hi=100;}
var gl=el.querySelector('.gl'),gd=el.querySelector('.gd'),tip=el.querySelector('.tip');
function show(x){var r=el.getBoundingClientRect(),p=Math.min(1,Math.max(0,(x-r.left)/r.width)),i=Math.round(p*(n-1));
var left=i/Math.max(n-1,1)*100,y=4+(1-(s.v[i]-lo)/((hi-lo)||1))*(r.height-8);
gl.style.left=left+'%';gd.style.left=left+'%';gd.style.top=y+'px';
tip.textContent=s.d[i].replace(/-/g,'.')+'  '+f(s.v[i],s.u);tip.style.left=Math.min(Math.max(left,14),86)+'%';el.classList.add('on');}
el.addEventListener('pointermove',function(e){show(e.clientX);});
el.addEventListener('pointerdown',function(e){show(e.clientX);});
el.addEventListener('pointerleave',function(){el.classList.remove('on');});
})(els[k]);}
})();"""


def render(lab, daily, latest_daily_url=None):
    """블로거 페이지 본문(style + div + script). lab·daily 중 없는 쪽은 그 칸을 빼고 그린다."""
    dd = f"장 마감 후 지표 {md(daily['asof'])} 기준" if daily else "장 마감 후 지표 준비 중"
    # 시장 지표 기준일 = 한국 공포탐욕(=시장 폭·국내 확정 종가) 날짜. meta.asof는 24시간 거래 항목(환율 등)의
    # 날짜라 하루 앞설 수 있어 머리에 쓰면 국내 지표까지 그날 값으로 오해한다.
    kr = next((g for g in lab["gauges"] if g["id"] == "KR"), None) if lab else None
    ld = (f"시장 지표 {md((kr or {'dates': [lab['meta']['asof']]})['dates'][-1])} 기준 · 평일 아침 갱신"
          if lab else "시장 지표 준비 중")
    parts = [f'<div class="sbd"><header class="hd"><div><h2>시드업 시장 현황판</h2>'
             f'<p class="sub">국내 증시의 오늘 체력과 시장 온도를 한 화면에</p></div>'
             f'<div class="upd"><span><i class="dot"></i>{dd}</span><span><i class="dot w"></i>{ld}</span></div></header>']
    if lab:   # 공포탐욕지수를 맨 위에 (2026-10-28 총괄 요청)
        parts += [sec_fg(lab), sec_now(lab)]
    if daily:
        parts += [sec_index(daily), sec_breadth(daily), sec_sectors(daily), sec_mcap(daily)]
    if lab:
        parts += [sec_chips(lab), sec_cards(lab)]
    parts += [sec_terms(), links(latest_daily_url), "</div>"]
    return f"<style>{CSS}</style>\n" + "\n".join(parts) + f"\n<script>{JS}</script>"
