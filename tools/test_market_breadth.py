# -*- coding: utf-8 -*-
"""국내 데일리 '시장 내부 체력' 표 검증 — Anthropic API 호출 0건.

실행: cd auto_publisher && python tools/test_market_breadth.py
  - 실제 네이버 전종목 시세로 시장폭을 계산하고 산술 정합성을 확인
  - 표를 본문 정해진 자리([당일 주도 섹터 및 테마] 앞)에 끼우는지, 자리 못 찾을 때·
    데이터 없을 때 본문을 그대로 두는지(발행 계속) 확인
  - 미리보기 HTML을 tools/_out/breadth_preview.html로 저장
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "jobs" / "kr_daily"))
try:
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
except Exception:
    pass

# 크레딧 보호 — 실수로 API를 부르면 즉시 드러나게
_anth = types.ModuleType("anthropic")
class _NoAPI:
    def __init__(self, *a, **k):
        pass
    @property
    def messages(self):
        raise RuntimeError("테스트 중 Anthropic API 호출 금지")
_anth.Anthropic = _NoAPI
sys.modules["anthropic"] = _anth
# FDR 스텁 — 드라이브 동기화 환경에서 임포트가 느리고, 이 경로는 FDR을 쓰지 않는다
_fdr = types.ModuleType("FinanceDataReader")
_fdr.DataReader = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("FDR 호출 금지"))
_fdr.StockListing = lambda *a, **k: None
sys.modules["FinanceDataReader"] = _fdr

from data_collector import _build_stock_maps          # noqa: E402
from ai_writer import insert_breadth_block, build_breadth_block_html  # noqa: E402
from shared.utils import md_to_html, fetch_naver_index_history       # noqa: E402

results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"  {'OK ' if ok else 'NG '} {label}" + (f" — {detail}" if detail else ""))


print("[1] 실제 전종목 시세로 시장폭 계산")
maps = _build_stock_maps()
mb = maps.get("market_breadth", {})
check("KOSPI·KOSDAQ 둘 다 계산됨", set(mb) == {"KOSPI", "KOSDAQ"}, str(list(mb)))
for name, m in mb.items():
    check(f"{name} 상승+하락+보합 = 전체", m["up"] + m["down"] + m["flat"] == m["total"],
          f"{m['up']}+{m['down']}+{m['flat']}={m['total']}")
    calc = round(m["up"] / m["total"] * 100, 1)
    check(f"{name} 상승 비율 검산", calc == m["up_ratio"], f"{m['up']}÷{m['total']}={calc}% vs {m['up_ratio']}%")
    check(f"{name} 거래대금 집중도 0-100%", 0 < m.get("top10_share", -1) <= 100, f"{m.get('top10_share')}%")
    check(f"{name} 종목 수가 상식 범위", 500 < m["total"] < 2500, f"{m['total']}종목")

data = {"market_breadth": mb}
for key, idx in (("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")):
    h = fetch_naver_index_history(idx, days=3)
    data[key] = {"change_pct": h[-1]["change_pct"]} if h else {}

print("\n[2] 본문 끼우기 — 정해진 자리")
md = """### 📊 1. 시장 지표 종합

#### [국내 증시 마감 지수]
| 지수명 | 마감 지수 | 등락률 | 주요 움직임 |
| :--- | :--- | :--- | :--- |
| **KOSPI** | 6,464.48pt | -2.44% | 예시 |

지수 해석 문장.

#### [당일 주도 섹터 및 테마]
| 주도 섹터 | 등락률 | 대표 종목 | 핵심 흐름 한 줄 |
| :--- | :--- | :--- | :--- |
| 예시섹터 | +1.00% | — | 예시 |

---

### 💥 2. 오늘 시장의 특징주
- 예시
"""
html = md_to_html(md)
out = insert_breadth_block(html, data)
pos_block = out.find("[시장 내부 체력]")
pos_sector = out.find("[당일 주도 섹터 및 테마]")
pos_index = out.find("[국내 증시 마감 지수]")
check("표가 들어감", pos_block > 0)
check("지수 표 다음, 섹터 표 앞에 위치", pos_index < pos_block < pos_sector,
      f"지수 {pos_index} < 체력 {pos_block} < 섹터 {pos_sector}")
check("표는 한 번만 들어감", out.count("[시장 내부 체력]") == 1)

print("\n[3] 예외 처리 — 발행은 계속")
no_sector = md_to_html(md.replace("#### [당일 주도 섹터 및 테마]", "#### [다른 소제목]"))
fb = insert_breadth_block(no_sector, data)
check("섹터 소제목이 없으면 특징주 섹션 앞에 넣음", fb.find("[시장 내부 체력]") < fb.find("💥 2."))
neither = "<p>소제목 없는 본문</p>"
check("넣을 자리가 없으면 본문 그대로", insert_breadth_block(neither, data) == neither)
check("시장폭 데이터 없으면 본문 그대로", insert_breadth_block(html, {"market_breadth": {}}) == html)
check("KOSDAQ만 실패해도 KOSPI 행은 나감",
      "KOSPI" in build_breadth_block_html({"market_breadth": {"KOSPI": mb["KOSPI"]}, "kospi": data["kospi"]}))

outdir = REPO / "tools" / "_out"
outdir.mkdir(exist_ok=True)
(outdir / "breadth_preview.html").write_text(
    '<!doctype html><meta charset="utf-8"><body style="max-width:760px;margin:24px auto;'
    "font-family:-apple-system,'Malgun Gothic',sans-serif;\">" + out + "</body>", encoding="utf-8")
print(f"\n미리보기: {outdir / 'breadth_preview.html'}")
print("\n실측값:")
for k, m in mb.items():
    print(f"  {k}: {m}  지수 {data[k.lower()].get('change_pct')}%")
bad = results.count(False)
print(f"\n총 {len(results)}건 / 실패 {bad}건")
sys.exit(1 if bad else 0)
