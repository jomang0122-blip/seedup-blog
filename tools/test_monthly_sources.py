# -*- coding: utf-8 -*-
"""월간 결산 데이터 소스 검증 — FDR 지수·환율 중단 대응이 실제로 동작하는지 확인한다.

왜 필요한가:
  FDR의 지수(KS11·KQ11)가 2026-09-08부터 갱신을 멈췄고 환율(USD/KRW)도
  2거래일 밀려 있었다. 개별 종목은 정상이라 겉으로 티가 안 나고, 실행도
  "성공"으로 끝난다. 월간 결산은 한 달에 한 번만 돌아서 사고가 나면
  다음 달까지 확인할 방법이 없으므로, 이 경로를 강제로 실행해 둔다.

  특히 거래대금은 단위가 바뀌는 지점이다 — 네이버 표는 백만원, 우리 코드는
  원. 100만배 차이가 나도 숫자는 그럴듯해 보이므로 크기까지 검사한다.

실행:
    cd auto_publisher
    python tools/test_monthly_sources.py

  로컬에서는 시스템 파이썬으로 돌리는 편이 빠르다 — 구글 드라이브 동기화
  폴더의 .venv는 requests 같은 패키지 최초 임포트만으로도 수 분이 걸려
  테스트가 타임아웃으로 죽는다(2026-09-10 실측). 이 테스트가 쓰는 requests·
  bs4·pytz는 시스템 파이썬에도 있다.

주의: 실제 발행은 하지 않는다. 조회와 대조만 수행한다.
"""
import json
import sys
import types
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# FinanceDataReader 스텁 — 드라이브 동기화 venv에서 임포트가 수 분 걸린다.
# 이번에 검증할 지수·환율·거래대금 경로는 FDR을 쓰지 않아야 하므로,
# 실수로 부르면 즉시 예외로 드러나게 해 둔다.
if "FinanceDataReader" not in sys.modules:
    _stub = types.ModuleType("FinanceDataReader")
    _stub.DataReader = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("테스트 스텁 — 지수·환율 경로는 FDR을 쓰지 않아야 한다"))
    _stub.StockListing = lambda *a, **k: None
    sys.modules["FinanceDataReader"] = _stub

from shared.utils import (  # noqa: E402
    fetch_naver_index_history, fetch_naver_fx_history,
    fetch_naver_index_trading_value_today, record_trading_value_snapshot,
    load_trading_value_history,
)

import time  # noqa: E402

results = []
_T0 = time.time()


def check(label: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(f"  {'OK ' if ok else 'NG '} [{time.time() - _T0:5.1f}s] {label}"
          + (f" — {detail}" if detail else ""))


def step(label: str):
    """구간 진입 시각을 남긴다 — 어디서 오래 걸리는지 바로 보이게."""
    print(f"\n[{time.time() - _T0:5.1f}s] {label}")


def _raw(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Referer": "https://m.stock.naver.com/"})
    return json.load(urllib.request.urlopen(req, timeout=20))


step("[1] 지수 이력 페이징 — 60행 상한을 넘겨도 이어붙는다")
for days in (45, 300):
    h = fetch_naver_index_history("KOSPI", days=days)
    if days == 300:
        _deep = h
    check(f"days={days} 요청 시 {days}행 근접 확보", len(h) >= days * 0.9,
          f"{len(h)}행 ({h[0]['date']} ~ {h[-1]['date']})")
    check(f"days={days} 날짜 중복 없음", len({x['date'] for x in h}) == len(h))
    check(f"days={days} 과거→최신 정렬", h == sorted(h, key=lambda x: x["date"]))

check("전년 12월까지 도달(YTD 기준값 확보 가능)",
      any(x["date"] <= "2025-12-31" for x in _deep),
      f"가장 오래된 날짜 {_deep[0]['date']}")

print("\n[2] 거래대금 — 오늘 스냅샷 + 로컬 누적 로그 (2026-10-06: sise_index_day.naver"
      " 영구 410으로 소급조회 불가해 '오늘 1건씩 쌓기' 방식으로 교체)")
today_val = fetch_naver_index_trading_value_today("KOSPI")
check("오늘 거래대금 조회됨", today_val is not None, f"{today_val}")
if today_val is not None:
    check("단위가 원 (조원 규모)", 1e12 <= today_val <= 1e15,
          f"{today_val:,.0f}원 = {today_val/1e12:.1f}조원")

# record/load 라운드트립은 실제 운영 로그(data/kr_trading_value_log.json)를
# 건드리면 안 되므로 임시 경로로 바꿔치기해서 검증한다.
import shared.utils as _u  # noqa: E402
import tempfile
_orig_path_fn = _u._trading_value_log_path
_tmp_log = Path(tempfile.gettempdir()) / "test_kr_trading_value_log.json"
if _tmp_log.exists():
    _tmp_log.unlink()
_u._trading_value_log_path = lambda: _tmp_log
try:
    record_trading_value_snapshot("KOSPI", "2026-01-02", 1.23e13)
    record_trading_value_snapshot("KOSPI", "2026-01-05", 2.34e13)
    loaded = load_trading_value_history("KOSPI")
    check("기록한 두 날짜가 그대로 로드됨",
          loaded.get("2026-01-02") == 1.23e13 and loaded.get("2026-01-05") == 2.34e13,
          str(loaded))
    check("다른 지수(KOSDAQ)는 비어 있음(섞이지 않음)",
          load_trading_value_history("KOSDAQ") == {}, "")
finally:
    _u._trading_value_log_path = _orig_path_fn
    if _tmp_log.exists():
        _tmp_log.unlink()

print("\n[3] 환율 — FDR 지연(09-08) 이후 날짜까지 온다")
fx = fetch_naver_fx_history(days=45)
check("환율 이력 수집됨", len(fx) >= 20, f"{len(fx)}일")
if fx:
    check("FDR 지연일(2026-09-08) 이후 데이터 존재", fx[-1]["date"] > "2026-09-08",
          f"마지막 {fx[-1]['date']} {fx[-1]['close']:,.2f}원")
    # pageSize를 너무 작게 주면 네이버가 HTTP 400을 낸다(5는 거절, 10·45는 정상 — 실측).
    # 비교는 오늘이 아니라 전 거래일로 한다 — 오늘 환율은 장중에 계속 움직인다.
    raw_fx = {r["localTradedAt"]: float(r["closePrice"].replace(",", ""))
              for r in _raw("https://m.stock.naver.com/front-api/marketIndex/prices"
                            "?category=exchange&reutersCode=FX_USDKRW"
                            "&page=1&pageSize=10")["result"]}
    settled = [h for h in fx if h["date"] < max(raw_fx)]
    if settled:
        last = settled[-1]
        check("전 거래일 환율 값 일치", abs(last["close"] - raw_fx.get(last["date"], -1)) < 0.01,
              f"{last['date']}: {last['close']} vs {raw_fx.get(last['date'])}")

print("\n[4] 월간 수집 함수 — 지난달 구간으로 실제 실행")
sys.path.insert(0, str(REPO / "jobs" / "kr_monthly"))
import data_collector as mo  # noqa: E402

today = datetime.today()
last_month_end = today.replace(day=1) - __import__("datetime").timedelta(days=1)
m_start = last_month_end.replace(day=1).strftime("%Y%m%d")
m_end = last_month_end.strftime("%Y%m%d")
print(f"    대상 구간: {m_start} ~ {m_end}")

idx = mo.get_index_data_monthly(m_start, m_end)
for key in ("kospi", "kosdaq"):
    d = idx.get(key) or {}
    ok = bool(d.get("close")) and bool(d.get("month_start_close"))
    check(f"{key} 월간 등락률 산출", ok,
          f"{d.get('month_start_close')} → {d.get('close')} ({d.get('monthly_pct')}%)" if ok else "비어 있음")
    if ok:
        calc = round((d["close"] - d["month_start_close"]) / d["month_start_close"] * 100, 2)
        check(f"{key} 월간 등락률 검산", abs(calc - d["monthly_pct"]) < 0.02,
              f"직접계산 {calc} vs 반환 {d['monthly_pct']}")

for ticker in ("KS11", "KQ11"):
    pct = mo.get_kospi_daily_pct_monthly(m_start, m_end, ticker=ticker)
    check(f"{ticker} 일별 등락률 산출", len(pct) >= 15, f"{len(pct)}일")
    if pct:
        check(f"{ticker} 모든 날짜가 해당 월", all(m_start <= p["date"].replace("-", "") <= m_end for p in pct),
              f"{pct[0]['date']} ~ {pct[-1]['date']}")

extra = mo.get_index_extra_monthly(m_start, m_end)
for key in ("kospi", "kosdaq"):
    e = extra.get(key) or {}
    check(f"{key} 월중 고저 산출", bool(e.get("month_high")) and bool(e.get("month_low")),
          f"{e.get('month_low')} ~ {e.get('month_high')} ({e.get('month_range_pct')}%)")
    # 거래대금은 2026-10-06부터 매일 1건씩 쌓는 방식이라, 누적 로그가 아직
    # 없으면 이번 달·전월 모두 "데이터 없음"이 정상이다 — 있으면 값을, 없으면
    # 생략됐는지만 확인한다(실패 취급 안 함).
    if e.get("avg_amount") is not None:
        check(f"{key} 일평균 거래대금 산출", True,
              f"{e['avg_amount']/1e12:.1f}조원 (전월 대비 {e.get('amount_change_pct')}%)")
    else:
        print(f"  --  [{key}] 일평균 거래대금: 누적 로그 데이터 없음(정상 — 축적 중)")
    check(f"{key} YTD 산출", e.get("ytd_pct") is not None,
          f"기준 {e.get('ytd_base_close')} → {e.get('ytd_pct')}%")

fxm = mo.get_fx_monthly(m_start, m_end)
check("환율 월간 산출", bool(fxm.get("close")),
      f"{fxm.get('start_close')} → {fxm.get('close')} ({fxm.get('monthly_pct')}%)")

print("\n" + "=" * 60)
bad_n = results.count(False)
print(f"총 {len(results)}건 검사 / 실패 {bad_n}건")
sys.exit(1 if bad_n else 0)
