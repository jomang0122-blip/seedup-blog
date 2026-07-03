# -*- coding: utf-8 -*-
"""
SeedUP 미증시 데일리 자동 발행 파이프라인
실행: python jobs/us_daily/main.py [--dry-run] [--force]
"""
import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import pytz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from data_collector import collect_all
from ai_writer import generate_post
from shared.utils import DISCLAIMER, md_to_html, apply_color_spans
from shared.validator import validate_post, apply_corrections
from shared.blog_publisher import publish_post, check_today_post

KST = pytz.timezone("Asia/Seoul")
REPO_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


_HOLIDAY_KR = {
    "New Year's Day": "새해 첫날",
    "Martin Luther King Jr. Day": "마틴 루터 킹 데이",
    "Washington's Birthday": "대통령의 날",
    "Good Friday": "성금요일",
    "Memorial Day": "메모리얼 데이",
    "Juneteenth National Independence Day": "준틴스 데이",
    "Independence Day": "독립기념일",
    "Labor Day": "노동절",
    "Thanksgiving Day": "추수감사절",
    "Christmas Day": "성탄절",
}
_WD_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _date_kor(d) -> str:
    return f"{str(d.year)[2:]}년 {d.month}월 {d.day}일"


def _already_published_us_date(us_date: str) -> bool:
    """logs/에서 같은 us_date로 발행된 기록이 있는지 확인 (휴장 감지 기반)."""
    for f in LOG_DIR.glob("us_daily_*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            if rec.get("us_date") == us_date and rec.get("url"):
                return True
        except Exception:
            continue
    return False


def _missed_us_weekdays(us_date: str, today_et=None) -> list:
    """마지막 거래일 이후 ~ 현재 ET 날짜까지 사이의 미국 평일 목록 = 휴장일 후보."""
    from datetime import timedelta
    import pytz as _pytz
    if today_et is None:
        today_et = datetime.now(_pytz.timezone("America/New_York")).date()
    last = datetime.strptime(us_date, "%Y-%m-%d").date()
    out, d = [], last + timedelta(days=1)
    while d <= today_et:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _holiday_name_kr(d) -> str:
    name = None
    try:
        import holidays as _hol
        name = _hol.financial_holidays("XNYS", years=d.year).get(d)
    except Exception:
        pass
    if not name:
        return "미국 증시 휴일"
    observed = name.endswith(" (observed)")
    base = name.replace(" (observed)", "")
    kr = _HOLIDAY_KR.get(base, base)
    return f"{kr}(대체휴일)" if observed else kr


def _next_open_et(after):
    """휴장일 다음의 첫 개장일(ET) — 주말·연속 휴일 건너뜀."""
    from datetime import timedelta
    try:
        import holidays as _hol
        cal = _hol.financial_holidays("XNYS", years=[after.year, after.year + 1])
    except Exception:
        cal = {}
    d = after + timedelta(days=1)
    while d.weekday() >= 5 or d in cal:
        d += timedelta(days=1)
    return d


def build_holiday_post(data: dict, missed: list) -> dict:
    """휴장 안내 포스팅 — AI 없이 Python 템플릿 (환각 원천 차단)."""
    from datetime import timedelta
    first = missed[0]
    reason = _holiday_name_kr(first)
    next_open = _next_open_et(missed[-1])
    next_report_kst = next_open + timedelta(days=1)

    def _md(d):
        return f"{d.month}월 {d.day}일({_WD_KR[d.weekday()]})"

    holiday_days_str = ", ".join(_md(d) for d in missed)
    title = f"[{_date_kor(first)} 미증시 휴장] {reason} 휴장 안내"

    prev_date = datetime.strptime(data["us_date"], "%Y-%m-%d").date()
    index_rows = "\n".join(
        f"| {v['name']} | {v['close']:,.2f} | {v['change_pct']:+.2f}% |"
        for v in data.get("indices", {}).values()
        if v.get("close") is not None and v.get("change_pct") is not None
    )

    md_body = f"""📌 **오늘 미국증시 핵심**
미국 증시는 {holiday_days_str} {reason}로 휴장했습니다. 다음 개장은 미국 동부 {_md(next_open)}이며, 마감 시황은 한국시간 {_md(next_report_kst)} 아침에 전해드립니다.

### 📅 휴장 안내

| 구분 | 내용 |
|------|------|
| 휴장일 | {holiday_days_str} |
| 휴장 사유 | {reason} |
| 다음 개장일 | 미국 동부 {_md(next_open)} |
| 다음 마감 시황 | 한국시간 {_md(next_report_kst)} 아침 발행 예정 |

### 📊 직전 거래일 요약 ({_md(prev_date)} 마감)

| 지수 | 종가 | 등락률 |
|------|------|--------|
{index_rows}

휴장 기간에는 새로운 거래 데이터가 없어 시황 분석을 생략합니다. 편안한 하루 보내세요!"""

    content = apply_color_spans(md_to_html(md_body)) + "\n" + DISCLAIMER
    return {
        "title": title,
        "content": content,
        "char_count": len(content),
        "labels": ["미국증시", "데일리", "휴장", "시황"],
    }


def _build_labels(data: dict) -> list:
    """라벨을 Python에서 고정 생성 — AI에게 맡기지 않음"""
    base = ["미국증시", "데일리", "시황", "미국주식", "나스닥", "S&P500", "뉴욕증시"]
    mover_labels = [m["ticker"] for m in data.get("top_movers", [])[:2]]
    return base + mover_labels


def build_title(data: dict) -> str:
    """제목을 Python에서 강제 조립 — AI에게 맡기지 않음"""
    us_date = data.get("us_date", "")
    try:
        d = datetime.strptime(us_date, "%Y-%m-%d")
        date_kor = f"{str(d.year)[2:]}년 {d.month}월 {d.day}일"
    except Exception:
        date_kor = us_date

    ixic = data["indices"].get("^IXIC", {})
    nasdaq_pct = ixic.get("change_pct", 0) or 0
    nasdaq_dir = "상승" if nasdaq_pct >= 0 else "하락"

    fixed = data.get("fixed_stocks", {})
    if fixed:
        top = max(fixed.values(), key=lambda x: abs(x.get("change_pct", 0)))
        stock_part = f", {top['name']} {top['change_pct']:+.1f}%"
    else:
        stock_part = ""

    return f"[{date_kor} 미증시 마감] 나스닥 {abs(nasdaq_pct):.1f}% {nasdaq_dir}{stock_part}"


def save_log(data: dict, post: dict, result: dict, kst_date: str, validation_issues: list = None):
    log_file = LOG_DIR / f"us_daily_{kst_date.replace('-', '')}.json"
    record = {
        "kst_date": kst_date,
        "us_date": data.get("us_date"),
        "published_at": datetime.now().isoformat(),
        "title": post.get("title", ""),
        "url": result.get("url", ""),
        "char_count": post.get("char_count", 0),
        "nasdaq_close": data["indices"].get("^IXIC", {}).get("close"),
        "nasdaq_change_pct": data["indices"].get("^IXIC", {}).get("change_pct"),
        "validation_issues": validation_issues or [],
    }
    log_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"로그 저장: {log_file.name}")


def run(dry_run: bool = False, force: bool = False):
    kst_now = datetime.now(KST)
    kst_date = kst_now.strftime("%Y-%m-%d")

    log("=" * 50)
    log(f"SeedUP 미증시 데일리  {'[DRY-RUN]' if dry_run else '[LIVE]'}  KST {kst_now.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 50)

    log("▶ Step 1: 미국 시장 데이터 수집")
    try:
        data = collect_all()
    except Exception as e:
        log(f"  [오류] 데이터 수집 실패: {e}")
        sys.exit(1)

    if data.get("market_closed"):
        log("  미국 증시 휴장일 — 발행 생략")
        sys.exit(0)

    if not data["indices"].get("^IXIC", {}).get("close"):
        log("  [오류] 나스닥 지수 누락 — 품질 게이트: 발행 중단")
        sys.exit(1)

    ixic = data["indices"].get("^IXIC", {})
    log(f"  미국 거래일: {data['us_date']}")
    log(f"  나스닥: {ixic.get('close', 'N/A')} ({ixic.get('change_pct', 0):+.2f}%)")
    log(f"  수집 종목: {len(data['fixed_stocks'])}개  급등락: {len(data['top_movers'])}개  뉴스: {len(data['news'])}건")

    # 휴장 감지: 마지막 거래일 리포트가 이미 발행됐으면 신규 마감 데이터 없음
    if _already_published_us_date(data["us_date"]):
        missed = _missed_us_weekdays(data["us_date"])
        if not missed:
            log(f"  {data['us_date']} 마감 리포트 이미 발행 — 신규 데이터 없음, 종료")
            sys.exit(0)
        log(f"  휴장 감지: {[d.isoformat() for d in missed]} — 휴장 안내 발행 모드")
        post = build_holiday_post(data, missed)
        log(f"  제목: {post['title']}")

        if dry_run:
            log("▶ [DRY-RUN] 발행 생략 — 미리보기")
            print(f"\n제목: {post['title']}\n\n{post['content'][:500]}...(이하 생략)")
            return

        if not force:
            try:
                existing = check_today_post(kst_date, label_filter="미증시 휴장]")
                if existing:
                    log(f"  오늘 휴장 안내 이미 발행됨 — 생략: {existing['url']}")
                    sys.exit(0)
            except Exception as e:
                log(f"  [경고] 중복 체크 실패 (발행은 계속): {e}")

        try:
            result = publish_post(
                title=post["title"], content=post["content"],
                labels=post["labels"], status="LIVE",
            )
            log(f"  휴장 안내 발행 완료: {result['url']}")
            save_log(data, post, result, kst_date, [])
        except Exception as e:
            log(f"  [오류] 휴장 안내 발행 실패: {e}")
            sys.exit(1)
        return

    log("▶ Step 2: 제목 조립 (Python 강제)")
    title = build_title(data)
    log(f"  제목: {title}")

    log("▶ Step 3: AI 블로그 콘텐츠 생성")
    try:
        post = generate_post(data)
        post["title"] = title              # Python 조립 제목으로 덮어쓰기
        post["labels"] = _build_labels(data)  # Python 고정 라벨로 덮어쓰기
        if not post["content"]:
            raise ValueError("콘텐츠가 비어 있습니다.")
        log(f"  글자수: {post['char_count']}자")
    except Exception as e:
        log(f"  [오류] 콘텐츠 생성 실패: {e}")
        sys.exit(1)

    log("▶ Step 3-1: 수치 검증")
    validation_issues = []
    try:
        validation = validate_post(data, post)
        if validation["approved"]:
            log("  검증 통과 — 수치 이상 없음")
        else:
            validation_issues = validation["issues"]
            log(f"  오류 {len(validation['issues'])}개 발견 — 자동 수정 적용")
            for issue in validation["issues"]:
                log(f"     [{issue['type']}] {issue['description']}")
            post = apply_corrections(post, validation)
            log(f"  수정 후 제목: {post['title']}")
    except Exception as e:
        log(f"  [경고] 검증 실패 (발행은 계속): {e}")

    if dry_run:
        log("▶ [DRY-RUN] 발행 생략 — 미리보기")
        print("\n" + "─" * 60)
        print(f"제목: {post['title']}")
        print(f"라벨: {post['labels']}")
        print(f"\n{post['content'][:500]}...(이하 생략)")
        print("─" * 60)
        log("DRY-RUN 완료")
        return

    log("▶ Step 4: 중복 발행 체크")
    if force:
        log("  --force 지정 — 중복 체크 생략")
    else:
        try:
            existing = check_today_post(kst_date, label_filter="미증시 마감]")
            if existing:
                log(f"  오늘 이미 발행됨 — 중복 발행 생략: {existing['url']}")
                sys.exit(0)
            log("  중복 없음 — 발행 진행")
        except Exception as e:
            log(f"  [경고] 중복 체크 실패 (발행은 계속): {e}")

    log("▶ Step 5: Blogger 발행")
    try:
        result = publish_post(
            title=post["title"],
            content=post["content"],
            labels=post.get("labels", ["미국증시", "데일리", "시황"]),
            status="LIVE",
        )
        log(f"  발행 완료!")
        log(f"  URL: {result['url']}")
        save_log(data, post, result, kst_date, validation_issues)
    except Exception as e:
        log(f"  [오류] 발행 실패: {e}")
        sys.exit(1)

    log("=" * 50)
    log("전체 파이프라인 완료")
    log("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 미증시 데일리 자동 발행")
    parser.add_argument("--dry-run", action="store_true", help="발행 없이 미리보기만")
    parser.add_argument("--force", action="store_true", help="중복 체크 무시하고 강제 재발행")
    args = parser.parse_args()
    run(dry_run=args.dry_run, force=args.force)
