# -*- coding: utf-8 -*-
"""
SeedUP 자동 블로그 발행 파이프라인
실행: python main.py [--dry-run] [--date YYYYMMDD]
"""
import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

# PowerShell 환경에서 한글 출력 깨짐 방지
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from data_collector import collect_all
from ai_writer import generate_post
from validator import validate_post, apply_corrections
from blog_publisher import publish_post

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def save_log(data: dict, post: dict, result: dict):
    date_str = data.get("date", datetime.today().strftime("%Y-%m-%d")).replace("-", "")
    log_file = LOG_DIR / f"{date_str}_post.json"
    record = {
        "date": data.get("date"),
        "published_at": datetime.now().isoformat(),
        "title": post["title"],
        "url": result.get("url", ""),
        "char_count": post["char_count"],
        "kospi_close": data.get("kospi", {}).get("close"),
        "kospi_change_pct": data.get("kospi", {}).get("change_pct"),
    }
    log_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"로그 저장: {log_file.name}")


def is_trading_day(date_str: str) -> bool:
    """해당 날짜에 코스피 거래 데이터가 있으면 True (공휴일·주말 감지)"""
    import FinanceDataReader as fdr
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    try:
        df = fdr.DataReader("KS11", date_fmt, date_fmt)
        return not df.empty
    except Exception:
        return False


def run(dry_run: bool = False, date: str = None):
    log("=" * 50)
    log(f"SeedUP 자동 발행 시작  {'[DRY-RUN]' if dry_run else '[LIVE]'}")
    log("=" * 50)

    # 공휴일·휴장일 체크 (날짜 미지정 = 오늘 자동 실행 모드에서만)
    if date is None:
        today = datetime.today().strftime("%Y%m%d")
        if not is_trading_day(today):
            log(f"  오늘({today})은 휴장일입니다 — 발행 생략")
            sys.exit(0)

    # 1. 데이터 수집
    log("▶ Step 1: 시장 데이터 수집")
    try:
        data = collect_all(date)
        kospi = data.get("kospi", {})
        log(f"  KOSPI: {kospi.get('close', 'N/A')} ({kospi.get('change_pct', 0):+.2f}%)")
        log(f"  급등 TOP1: {data['top_gainers'][0]['name'] if data['top_gainers'] else '없음'}")
    except Exception as e:
        log(f"  [오류] 데이터 수집 실패: {e}")
        sys.exit(1)

    # 2. AI 글 생성
    log("▶ Step 2: AI 블로그 포스팅 생성")
    try:
        post = generate_post(data)
        if not post["title"] or not post["content"]:
            raise ValueError("제목 또는 본문이 비어 있습니다.")
        log(f"  제목: {post['title']}")
        log(f"  글자수: {post['char_count']}자")
    except Exception as e:
        log(f"  [오류] 글 생성 실패: {e}")
        sys.exit(1)

    # 3. 수치 검증
    log("▶ Step 3: 수치 검증 에이전트")
    try:
        validation = validate_post(data, post)
        if validation["approved"]:
            log("  ✅ 검증 통과 — 수치 이상 없음")
        else:
            log(f"  ⚠️  오류 {len(validation['issues'])}개 발견 — 자동 수정 적용")
            for issue in validation["issues"]:
                log(f"     [{issue['type']}] {issue['description']}")
            post = apply_corrections(post, validation)
            log(f"  수정 후 제목: {post['title']}")
    except Exception as e:
        log(f"  [경고] 검증 실패 (발행은 계속): {e}")

    # 4. 발행 (dry-run이면 스킵)
    if dry_run:
        log("▶ Step 3: [DRY-RUN] 발행 생략 — 생성된 포스트 미리보기")
        print("\n" + "─" * 60)
        print(f"제목: {post['title']}")
        print(f"라벨: {post['labels']}")
        print(f"\n{post['content'][:500]}...(이하 생략)")
        print("─" * 60)
        log("DRY-RUN 완료")
        return

    log("▶ Step 4: Blogger 발행")
    try:
        result = publish_post(
            title=post["title"],
            content=post["content"],
            labels=post["labels"],
            status="LIVE",
        )
        log(f"  발행 완료!")
        log(f"  URL: {result['url']}")
        save_log(data, post, result)
    except Exception as e:
        log(f"  [오류] 발행 실패: {e}")
        sys.exit(1)

    log("=" * 50)
    log("✅ 전체 파이프라인 완료")
    log("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SeedUP 자동 블로그 발행")
    parser.add_argument("--dry-run", action="store_true",
                        help="발행하지 않고 생성된 포스트만 출력")
    parser.add_argument("--date", type=str, default=None,
                        help="날짜 지정 (YYYYMMDD). 기본값: 오늘")
    args = parser.parse_args()

    run(dry_run=args.dry_run, date=args.date)
