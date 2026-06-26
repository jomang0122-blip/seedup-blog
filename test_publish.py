# -*- coding: utf-8 -*-
"""
스케줄 동작 확인용 테스트 발행 스크립트
실행: python test_publish.py --type [kr_daily|us_daily|kr_weekly|us_weekly]
"""
import argparse
import io
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from blog_publisher import publish_post

LABELS_MAP = {
    "kr_daily":  ["테스트", "국내증시", "데일리"],
    "us_daily":  ["테스트", "미국증시", "데일리"],
    "kr_weekly": ["테스트", "국내증시", "위클리"],
    "us_weekly": ["테스트", "미국증시", "위클리"],
}

TYPE_NAME = {
    "kr_daily":  "국내증시 데일리",
    "us_daily":  "미국증시 데일리",
    "kr_weekly": "국내증시 위클리",
    "us_weekly": "미국증시 위클리",
}


def run(post_type: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name = TYPE_NAME.get(post_type, post_type)
    labels = LABELS_MAP.get(post_type, ["테스트"])

    title = f"[스케줄 테스트] {name} — {now}"
    content = f"""<p>이 글은 GitHub Actions 스케줄 동작 확인용 테스트 포스팅입니다.</p>
<p><strong>콘텐츠 타입:</strong> {name}</p>
<p><strong>실행 시각 (KST):</strong> {now}</p>
<p>스케줄이 정상 동작하면 이 글이 자동으로 발행됩니다.<br>
확인 후 수동으로 삭제해주세요.</p>
<hr>
<p><em>SeedUp INVEST 자동화 시스템 테스트</em></p>"""

    print(f"[{now}] 테스트 발행 시작: {name}")
    result = publish_post(title=title, content=content, labels=labels, status="LIVE")
    print(f"[{now}] 발행 완료!")
    print(f"  제목: {result['title']}")
    print(f"  URL : {result['url']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="스케줄 테스트 발행")
    parser.add_argument(
        "--type",
        required=True,
        choices=["kr_daily", "us_daily", "kr_weekly", "us_weekly"],
        help="발행 콘텐츠 타입",
    )
    args = parser.parse_args()
    run(args.type)
