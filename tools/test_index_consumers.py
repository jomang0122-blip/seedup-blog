# -*- coding: utf-8 -*-
"""지수를 쓰는 나머지 경로 검증 — 휴장 안내·백필·캔들차트.

왜 필요한가:
  FDR 지수 중단(2026-09-08~) 대응의 마지막 조각. 세 경로 모두 평소에는
  실행되지 않아 사고가 나도 한참 뒤에야 발견된다.
    - 휴장 안내의 "직전 거래일 요약" 표 → 국내 휴장일에만 (몇 달에 한 번)
    - 백필(--date) → 과거 복구 발행할 때만
    - 캔들차트 → 현재 호출부 없음(미사용)
  그래서 여기서 강제로 실행해 둔다(교훈 B071).

실행:
    cd auto_publisher
    python tools/test_index_consumers.py

  로컬에서는 시스템 파이썬을 쓴다 — 드라이브 동기화 .venv는 임포트가 매우 느리다.

주의: 실제 발행은 하지 않는다. 데이터 조회와 대조만 수행한다.
"""
import json
import sys
import types
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# FinanceDataReader 스텁 — 이 경로들은 더 이상 FDR을 쓰지 않아야 한다.
# 실수로 부르면 예외로 즉시 드러난다.
if "FinanceDataReader" not in sys.modules:
    _stub = types.ModuleType("FinanceDataReader")
    _stub.DataReader = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("테스트 스텁 — 이 경로는 FDR을 쓰지 않아야 한다"))
    _stub.StockListing = lambda *a, **k: None
    sys.modules["FinanceDataReader"] = _stub

# 무거운/선택적 의존성 스텁.
#  - 휴장 안내는 AI를 쓰지 않는 순수 템플릿이라 anthropic·ai_writer가 필요 없다.
#  - _fetch_ohlc는 pandas만 쓰고 그래프 라이브러리를 건드리지 않는데,
#    chart_generator가 모듈 최상단에서 matplotlib·mplfinance를 임포트한다.
#    시스템 파이썬에는 이 둘이 없을 수 있어(그래서 이 테스트가 한 번 죽었다)
#    데이터 경로만 검증할 수 있게 스텁으로 세운다.
for name, attrs in [("anthropic", {"Anthropic": lambda *a, **k: None}),
                    ("ai_writer", {"generate_post": lambda *a, **k: {},
                                   "KR_DAILY_REQUIRED_SECTIONS": []}),
                    ("matplotlib", {"use": lambda *a, **k: None}),
                    ("mplfinance", {"make_marketcolors": lambda *a, **k: None,
                                    "make_mpf_style": lambda *a, **k: None,
                                    "plot": lambda *a, **k: None})]:
    if name not in sys.modules:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m

results = []


def check(label: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(f"  {'OK ' if ok else 'NG '} {label}" + (f" — {detail}" if detail else ""))


def _naver_latest(index: str):
    req = urllib.request.Request(
        f"https://m.stock.naver.com/api/index/{index}/price?pageSize=10&page=1",
        headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=20))


print("[1] 휴장 안내 — 직전 거래일 요약 표")
sys.path.insert(0, str(REPO / "jobs" / "kr_daily"))
import main as kr  # noqa: E402

rows, last_date = kr._last_kr_index_snapshot()
print(f"    {rows} / 기준일 {last_date}")
check("KOSPI·KOSDAQ 두 줄 모두 확보", len(rows) == 2, f"{len(rows)}줄")
check("기준일이 FDR 중단일(2026-09-07)보다 최신",
      last_date is not None and last_date > datetime(2026, 9, 7).date(), str(last_date))
if rows:
    raw = {r["localTradedAt"]: r for r in _naver_latest("KOSPI")}
    kospi = [r for r in rows if r[0] == "KOSPI"]
    if kospi and str(last_date) in raw:
        want = float(raw[str(last_date)]["closePrice"].replace(",", ""))
        # 장중에 이 테스트를 돌리면 우리 함수와 검증용 조회 사이 몇 초 동안
        # 지수가 움직여 값이 어긋난다. 이 경로는 휴장일에만 실행되므로 실제
        # 발행 때는 마감된 값을 보고, 그때는 정확히 일치한다.
        # 그래서 여기서는 "같은 날짜의 같은 지수인가"만 느슨하게 확인한다.
        drift = abs(kospi[0][1] - want) / want * 100
        check("KOSPI 종가가 네이버 값과 일치(장중 변동 허용 0.5%)", drift < 0.5,
              f"{kospi[0][1]} vs {want} (차이 {drift:.3f}%)")

print("\n[2] 백필 — 과거 날짜 지수 조회")
import data_collector as dc  # noqa: E402

for back in (3, 30):
    target = datetime.today() - timedelta(days=back)
    got = dc.get_index_data_historical(target.strftime("%Y%m%d"))
    ok = bool(got.get("kospi", {}).get("close")) and bool(got.get("kosdaq", {}).get("close"))
    check(f"{back}일 전({target:%Y-%m-%d}) 지수 조회", ok,
          f"KOSPI {got.get('kospi', {}).get('close')} ({got.get('kospi', {}).get('change_pct')}%)")
    if ok:
        k = got["kospi"]
        check(f"{back}일 전 change 값 존재", k.get("change") is not None, str(k.get("change")))

# 백필이 "오늘 값"을 그대로 주지 않는지 — 이 함수가 존재하는 이유 자체가 그것이다
old = dc.get_index_data_historical((datetime.today() - timedelta(days=30)).strftime("%Y%m%d"))
now = dc.get_index_data_historical(datetime.today().strftime("%Y%m%d"))
check("30일 전 값과 오늘 값이 다르다(백필이 실제로 과거를 본다)",
      old.get("kospi", {}).get("close") != now.get("kospi", {}).get("close"),
      f"{old.get('kospi', {}).get('close')} vs {now.get('kospi', {}).get('close')}")

print("\n[3] 캔들차트 — OHLC 확보")
from shared.chart_generator import _fetch_ohlc  # noqa: E402

df = _fetch_ohlc("KS11", 30)
check("행 수 확보", len(df) >= 25, f"{len(df)}행")
check("OHLC 컬럼 존재", list(df.columns) == ["Open", "High", "Low", "Close"], str(list(df.columns)))
check("결측 없음", not df.isnull().values.any())
check("고가 >= 저가", bool((df["High"] >= df["Low"]).all()))
check("종가가 고저 사이", bool(((df["Close"] <= df["High"]) & (df["Close"] >= df["Low"])).all()))
check("마지막 날짜가 FDR 중단일보다 최신",
      str(df.index[-1].date()) > "2026-09-07", str(df.index[-1].date()))

print("\n" + "=" * 58)
bad = results.count(False)
print(f"총 {len(results)}건 검사 / 실패 {bad}건")
sys.exit(1 if bad else 0)
