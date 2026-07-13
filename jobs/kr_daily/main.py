# -*- coding: utf-8 -*-
"""
SeedUP 국내증시 데일리 자동 발행 파이프라인
실행: python jobs/kr_daily/main.py [--dry-run] [--date YYYYMMDD] [--force]
"""
import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from data_collector import collect_all
from ai_writer import generate_post
from shared.utils import DISCLAIMER, md_to_html, apply_color_spans
from shared.validator import validate_post, apply_corrections, apply_structural_fixes, assert_market_keywords
from shared.blog_publisher import publish_post, check_today_post

REPO_ROOT = Path(__file__).parent.parent.parent
LOG_DIR  = REPO_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def save_log(data: dict, post: dict, result: dict, validation_issues: list = None):
    date_str = data.get("date", datetime.today().strftime("%Y-%m-%d")).replace("-", "")
    log_file = LOG_DIR / f"kr_daily_{date_str}.json"
    record = {
        "date": data.get("date"),
        "published_at": datetime.now().isoformat(),
        "title": post["title"],
        "url": result.get("url", ""),
        "char_count": post["char_count"],
        "kospi_close": data.get("kospi", {}).get("close"),
        "kospi_change_pct": data.get("kospi", {}).get("change_pct"),
        "validation_issues": validation_issues or [],
    }
    log_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"로그 저장: {log_file.name}")


def is_trading_day(date_str: str) -> bool:
    import FinanceDataReader as fdr
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    try:
        df = fdr.DataReader("KS11", date_fmt, date_fmt)
        return not df.empty
    except Exception:
        return False


_WD_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _kr_holiday_name(d) -> str:
    """휴장 사유 이름 조회 — 실제 휴장 판정은 is_trading_day()가 담당."""
    try:
        import holidays as _hol
        name = _hol.KR(years=d.year).get(d)
        if name:
            return name
    except Exception:
        pass
    if d.month == 5 and d.day == 1:
        return "근로자의 날"
    if d.month == 12 and d.day == 31:
        return "연말 휴장일"
    return "임시 휴장"


def _next_kr_open(d):
    """다음 국내 증시 개장 예상일 — 주말·공휴일·근로자의날·연말휴장 건너뜀."""
    from datetime import timedelta
    try:
        import holidays as _hol
        kr = _hol.KR(years=[d.year, d.year + 1])
    except Exception:
        kr = {}
    nd = d + timedelta(days=1)
    while nd.weekday() >= 5 or nd in kr or (nd.month, nd.day) in [(5, 1), (12, 31)]:
        nd += timedelta(days=1)
    return nd


def _last_kr_index_snapshot():
    """직전 거래일 KOSPI/KOSDAQ 종가·등락률 (FDR 최근 데이터)."""
    from datetime import timedelta
    import FinanceDataReader as fdr
    rows = []
    last_date = None
    start = (datetime.today() - timedelta(days=14)).strftime("%Y-%m-%d")
    for code, name in [("KS11", "KOSPI"), ("KQ11", "KOSDAQ")]:
        try:
            s = fdr.DataReader(code, start)["Close"].dropna()
            if len(s) >= 2:
                close, prev = float(s.iloc[-1]), float(s.iloc[-2])
                rows.append((name, close, (close - prev) / prev * 100))
                last_date = s.index[-1].date()
        except Exception:
            continue
    return rows, last_date


def build_kr_holiday_post(today_d) -> dict:
    """국내 증시 휴장 안내 포스팅 — AI 없이 Python 템플릿 (환각 원천 차단)."""
    reason = _kr_holiday_name(today_d)
    next_open = _next_kr_open(today_d)

    def _md(d):
        return f"{d.month}월 {d.day}일({_WD_KR[d.weekday()]})"

    date_kor = f"{str(today_d.year)[2:]}년 {today_d.month}월 {today_d.day}일"
    title = f"[{date_kor} 국내증시 휴장] {reason} 휴장 안내"

    rows, last_date = _last_kr_index_snapshot()
    index_rows = "\n".join(
        f"| {name} | {close:,.2f} | {pct:+.2f}% |" for name, close, pct in rows
    )
    last_date_str = _md(last_date) if last_date else "직전 거래일"

    md_body = f"""📌 **오늘 국내증시 핵심**
오늘({_md(today_d)}) 국내 증시는 {reason}로 휴장합니다. 다음 개장은 {_md(next_open)}이며, 데일리 시황은 개장일 오후에 다시 찾아뵙겠습니다.

### 📅 휴장 안내

| 구분 | 내용 |
|------|------|
| 휴장일 | {_md(today_d)} |
| 휴장 사유 | {reason} |
| 다음 개장일 | {_md(next_open)} |
| 다음 데일리 시황 | {_md(next_open)} 오후 발행 예정 |

### 📊 직전 거래일 요약 ({last_date_str} 마감)

| 지수 | 종가 | 등락률 |
|------|------|--------|
{index_rows}

휴장일에는 새로운 거래 데이터가 없어 시황 분석을 생략합니다. 편안한 휴일 보내세요!"""

    content = apply_color_spans(md_to_html(md_body)) + "\n" + DISCLAIMER
    return {
        "title": title,
        "content": content,
        "char_count": len(content),
        "labels": ["국내증시", "데일리", "휴장", "시황"],
    }


def run(dry_run: bool = False, date: str = None, force: bool = False):
    log("=" * 50)
    log(f"SeedUP 국내증시 데일리  {'[DRY-RUN]' if dry_run else '[LIVE]'}")
    log("=" * 50)

    if date is None:
        today = datetime.today().strftime("%Y%m%d")
        if not is_trading_day(today):
            today_d = datetime.today().date()
            if today_d.weekday() >= 5:
                log(f"  오늘({today})은 주말입니다 — 발행 생략")
                sys.exit(0)

            log(f"  오늘({today})은 휴장일 — 휴장 안내 발행 모드")
            post = build_kr_holiday_post(today_d)
            log(f"  제목: {post['title']}")

            if dry_run:
                log("▶ [DRY-RUN] 발행 생략 — 미리보기")
                print(f"\n제목: {post['title']}\n\n{post['content'][:500]}...(이하 생략)")
                return

            if not force:
                try:
                    kst_today = datetime.today().strftime("%Y-%m-%d")
                    existing = check_today_post(kst_today, label_filter="국내증시 휴장]")
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
            except Exception as e:
                log(f"  [오류] 휴장 안내 발행 실패: {e}")
                sys.exit(1)
            return
    else:
        if not is_trading_day(date):
            log(f"  [오류] 지정한 날짜({date})는 거래일이 아닙니다(주말·공휴일) — 백필 중단")
            sys.exit(1)

    log("▶ Step 1: 시장 데이터 수집")
    try:
        data = collect_all(date)
        kospi = data.get("kospi", {})
        log(f"  KOSPI: {kospi.get('close', 'N/A')} ({kospi.get('change_pct', 0):+.2f}%)")
        log(f"  급등 TOP1: {data['top_gainers'][0]['name'] if data['top_gainers'] else '없음'}")
        log(f"  특징주 뉴스: {len(data.get('crawled_news_features', []))}건")
    except Exception as e:
        log(f"  [오류] 데이터 수집 실패: {e}")
        sys.exit(1)

    if not data.get("kospi", {}).get("close"):
        log("  [오류] KOSPI 지수 누락 — 품질 게이트: 발행 중단")
        sys.exit(1)

    if not data.get("kosdaq", {}).get("close"):
        log("  [오류] KOSDAQ 지수 누락 — 품질 게이트: 발행 중단")
        sys.exit(1)

    log("▶ Step 2: AI 블로그 포스팅 생성 + 검증 (반복서술·근거없는 창작 시 재생성, 최대 3회)")
    post = None
    validation_issues = []
    for attempt in range(3):
        try:
            candidate = generate_post(data)
            if not candidate["title"] or not candidate["content"]:
                raise ValueError("제목 또는 본문이 비어 있습니다.")
            log(f"  제목: {candidate['title']}")
            log(f"  글자수: {candidate['char_count']}자")
        except Exception as e:
            log(f"  [오류] 글 생성 실패: {e}")
            sys.exit(1)

        try:
            assert_market_keywords(candidate["content"], ["코스피", "KOSPI"], "국내증시(코스피)")
        except ValueError as e:
            log(f"  [경고] {e}")
            if attempt < 2:
                log(f"  [재시도 {attempt + 1}/3] 다른 시장 콘텐츠 의심 — 글 재생성")
                continue
            log("  [오류] 3회 모두 시장 키워드 검증 실패 — 발행 중단")
            sys.exit(1)

        log("▶ Step 3: 수치 검증 에이전트")
        try:
            validation = validate_post(data, candidate)
        except Exception as e:
            log(f"  [경고] 검증 실패 (발행은 계속): {e}")
            post = candidate
            break

        if validation["approved"]:
            log("  검증 통과 — 수치 이상 없음")
            post = candidate
            break

        validation_issues = validation["issues"]
        log(f"  오류 {len(validation['issues'])}개 발견")
        for issue in validation["issues"]:
            log(f"     [{issue['type']}] {issue['description']}")

        if validation.get("needs_regenerate") and attempt < 2:
            log(f"  [재시도 {attempt + 1}/3] 반복서술·근거없는 뉴스창작 감지 — 글 재생성")
            continue

        candidate = apply_corrections(candidate, validation)
        corr_log = candidate.pop("_correction_log", {"applied": [], "skipped": []})
        log(f"  수정 후 제목: {candidate['title']}")
        log(f"  본문 자동교정: 적용 {len(corr_log['applied'])}건 / 건너뜀 {len(corr_log['skipped'])}건")
        post = candidate
        break

    if post is None:
        log("  [오류] 3회 모두 검증 실패 — 발행 중단")
        sys.exit(1)

    log("▶ Step 3-1: 구조 검증 (색상 태그 중첩·면책조항 누락)")
    post["content"], structural_issues = apply_structural_fixes(post["content"])
    post["char_count"] = len(post["content"])
    if structural_issues:
        validation_issues.extend(structural_issues)
        for si in structural_issues:
            log(f"     [{si['type']}] {si['description']}")
    else:
        log("  구조 이상 없음")

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
            kst_today = datetime.today().strftime("%Y-%m-%d")
            existing = check_today_post(kst_today, label_filter="국내증시]")
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
            labels=post["labels"],
            status="LIVE",
        )
        log(f"  발행 완료!")
        log(f"  URL: {result['url']}")
        save_log(data, post, result, validation_issues)
    except Exception as e:
        log(f"  [오류] 발행 실패: {e}")
        sys.exit(1)

    log("=" * 50)
    log("전체 파이프라인 완료")
    log("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 국내증시 데일리 자동 발행")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run, date=args.date, force=args.force)
