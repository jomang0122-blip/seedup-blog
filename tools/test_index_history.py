# -*- coding: utf-8 -*-
"""지수 이력 조회 검증 — FDR 지수 중단(2026-09-08~) 대응이 실제로 동작하는지 확인한다.

왜 필요한가:
  FDR의 지수 데이터(KS11·KQ11)가 2026-09-08부터 갱신을 멈췄다. 개별 종목은
  정상이라 겉으로는 티가 안 나고, 실행도 "성공"으로 끝난다. 그래서 kr_daily는
  발행 날짜가 09-07에 고착됐고(9월 8일·9일 리포트가 둘 다 "9월 7일"로 발행),
  kr_weekly는 주간 일별 등락률 표에 틀린 값이 채워질 상황이었다.

  이 스크립트는 지수 이력이 오늘까지 오는지, 그리고 위클리의 두 계산이
  네이버 실제 값과 일치하는지를 매번 즉시 확인한다.

실행:
    cd auto_publisher
    ./.venv/Scripts/python.exe tools/test_index_history.py

주의: 실제 발행은 하지 않는다. 조회와 대조만 수행한다.
"""
import json
import sys
import types
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# 출력 버퍼링 해제 — 중간에 멈춰도 어디까지 갔는지 보이게 한다
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# FinanceDataReader 스텁 — 구글 드라이브 동기화 venv에서 임포트가 수 분 걸린다.
# 이번에 검증할 지수 경로는 FDR을 아예 쓰지 않으므로 스텁으로 충분하고,
# 개별 종목 경로(get_top_stocks_weekly)는 이 테스트가 호출하지 않는다.
# 지수 경로에서 실수로 FDR을 다시 부르면 즉시 예외로 드러난다.
if "FinanceDataReader" not in sys.modules:
    _stub = types.ModuleType("FinanceDataReader")
    _stub.DataReader = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("테스트 스텁 — 지수 경로는 FDR을 쓰지 않아야 한다"))
    _stub.StockListing = lambda *a, **k: None
    sys.modules["FinanceDataReader"] = _stub

from shared.utils import fetch_naver_index_history  # noqa: E402

results = []


def check(label: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(f"  {'OK ' if ok else 'NG '} {label}" + (f" — {detail}" if detail else ""))


def _naver_raw(index: str, size: int = 20):
    """검증용 별도 조회 — 우리 함수를 거치지 않고 원본 응답을 그대로 받는다."""
    req = urllib.request.Request(
        f"https://m.stock.naver.com/api/index/{index}/price?pageSize={size}&page=1",
        headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))


print("[1] 지수 이력이 최신 거래일까지 온다")
for index in ("KOSPI", "KOSDAQ"):
    hist = fetch_naver_index_history(index, days=20)
    check(f"{index} 행 수 확보", len(hist) >= 10, f"{len(hist)}행")
    check(f"{index} 과거→최신 정렬", hist == sorted(hist, key=lambda h: h["date"]),
          f"{hist[0]['date']} ~ {hist[-1]['date']}")
    raw_latest = _naver_raw(index, 3)[0]["localTradedAt"]
    check(f"{index} 마지막 날짜가 네이버 최신과 일치", hist[-1]["date"] == raw_latest,
          f"{hist[-1]['date']} (네이버 {raw_latest})")
    # FDR이 멈춘 날짜에 고착돼 있지 않은지 — 이번 사고의 핵심 지점
    check(f"{index} FDR 중단일(2026-09-07)에 고착되지 않음",
          hist[-1]["date"] > "2026-09-07", hist[-1]["date"])

print("\n[2] 종가·등락률이 네이버 원본과 값까지 일치한다")
# 오늘 행은 제외한다 — 장중에는 값이 계속 움직여서, 우리 함수와 검증용 조회
# 사이의 몇 초 차이만으로도 다른 값이 나온다(테스트만 흔들릴 뿐 운영에는
# 영향 없음: 위클리는 토요일, 데일리는 15:30 마감 뒤 16:30에 실행된다).
_today = _naver_raw("KOSPI", 1)[0]["localTradedAt"]
raw = {r["localTradedAt"]: r for r in _naver_raw("KOSPI", 20)}
mismatch = []
compared = 0
for h in fetch_naver_index_history("KOSPI", days=20):
    r = raw.get(h["date"])
    if not r or h["date"] >= _today:
        continue
    compared += 1
    if abs(h["close"] - float(r["closePrice"].replace(",", ""))) > 0.005:
        mismatch.append((h["date"], "종가"))
    if abs(h["change_pct"] - float(r["fluctuationsRatio"])) > 0.005:
        mismatch.append((h["date"], "등락률"))
check(f"마감된 {compared}개 거래일 값 일치", not mismatch,
      str(mismatch[:3]) if mismatch else f"{compared}일 전부 일치 (오늘 {_today} 제외)")

print("\n[3] 위클리 계산 — 최근 금~금 구간을 실제로 돌려본다")
sys.path.insert(0, str(REPO / "jobs" / "kr_weekly"))
import data_collector as wk  # noqa: E402

this_fri, prev_fri, _, _ = wk.get_week_dates()
print(f"    이번 금요일 {this_fri} / 이전 금요일 {prev_fri}")

idx = wk.get_index_data_weekly(this_fri, prev_fri)
for key in ("kospi", "kosdaq"):
    d = idx.get(key) or {}
    ok = bool(d) and d.get("prev_close") and d.get("close")
    check(f"{key} 주간 등락률 산출", bool(ok),
          f"{d.get('prev_close')} → {d.get('close')} ({d.get('weekly_pct')}%)" if ok else "비어 있음")
    if ok:
        # 검산: (이번 종가 - 이전 종가) / 이전 종가 × 100
        calc = round((d["close"] - d["prev_close"]) / d["prev_close"] * 100, 2)
        check(f"{key} 주간 등락률 검산", abs(calc - d["weekly_pct"]) < 0.02,
              f"직접계산 {calc} vs 반환 {d['weekly_pct']}")

def _check_daily_pct(label: str, fri: str, prev: str):
    pct = wk.get_kospi_daily_pct_weekly(fri, prev)
    print(f"    [{label}] {prev}~{fri} → {len(pct)}일: {pct}")
    check(f"{label} 일별 등락률 비어 있지 않음", bool(pct), f"{len(pct)}일")
    if not pct:
        return
    check(f"{label} 모든 날짜가 구간 안",
          all(prev <= d.replace("-", "") <= fri for d in pct), f"{min(pct)} ~ {max(pct)}")
    # 날짜별 값이 네이버 원본과 같은지 — "마지막 값 덮어쓰기" 버그의 재발 방지 지점.
    # 예전 코드는 시계열 마지막 칸에 금요일 종가를 덮어써서, FDR이 멈춘 날짜의
    # 등락률이 엉뚱한 값으로 바뀌었다. 오늘 행은 장중 변동이 있어 비교에서 뺀다.
    bad = [d for d, v in pct.items()
           if d in raw and d < _today and abs(v - float(raw[d]["fluctuationsRatio"])) > 0.005]
    check(f"{label} 날짜별 등락률이 네이버 원본과 일치(덮어쓰기 버그 없음)", not bad, str(bad))


_check_daily_pct("최근 주간", this_fri, prev_fri)

# FDR이 멈춘 구간(2026-09-08~)을 반드시 포함하는 창으로도 돌린다.
# get_week_dates()는 실행 요일에 따라 창이 바뀌어서, 실행 시점에 따라 정작
# 고장난 구간을 한 번도 안 짚고 지나갈 수 있다 — 이번 실행이 실제로 그랬다.
_check_daily_pct("FDR 중단구간 포함", "20260910", "20260903")

pct_dead = wk.get_kospi_daily_pct_weekly("20260910", "20260903")
check("FDR 중단 이후 날짜(09-08 이후)가 실제로 채워짐",
      any(d > "2026-09-07" for d in pct_dead),
      f"채워진 날짜: {sorted(d for d in pct_dead if d > '2026-09-07')}")

print("\n" + "=" * 58)
bad_n = results.count(False)
print(f"총 {len(results)}건 검사 / 실패 {bad_n}건")
sys.exit(1 if bad_n else 0)
