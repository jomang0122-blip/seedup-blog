# -*- coding: utf-8 -*-
"""국내·미국 데일리/위클리 발행글 로컬 아카이브 스크립트.

Blogger에서 4개 라벨(국내데일리·국내위클리·미국데일리·미국위클리) 글을 내려받아
01_국내증시/01_발행글/, 02_미국증시/01_발행글/ 에 저장한다.
데일리는 월별(YYYY-MM) 하위폴더로 정리하고, 이미 받은 글은 건너뛴다(증분).

실행:
    cd auto_publisher
    ./.venv/Scripts/python.exe tools/archive_market_posts.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from shared.auth import get_credentials
from googleapiclient.discovery import build

BLOG_ID = '2047573422787647052'
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
KR_ROOT = os.path.abspath(os.path.join(REPO_ROOT, '..'))            # 01_국내증시
US_ROOT = os.path.abspath(os.path.join(REPO_ROOT, '..', '..', '02_미국증시'))

# 라벨 → (저장 루트, 데일리 여부: 월별 하위폴더 사용)
LABEL_MAP = {
    '국내데일리': (os.path.join(KR_ROOT, '01_발행글', '데일리'), True),
    '국내위클리': (os.path.join(KR_ROOT, '01_발행글', '위클리'), False),
    '미국데일리': (os.path.join(US_ROOT, '01_발행글', '데일리'), True),
    '미국위클리': (os.path.join(US_ROOT, '01_발행글', '위클리'), False),
}


def sanitize(title: str) -> str:
    t = re.sub(r'^\[[^\]]+\]\s*', '', title)
    t = re.sub(r'[\\/:*?"<>|]', '', t)
    return t.replace(' ', '').strip()[:40]


def collect_existing_ids(root: str) -> set:
    ids = set()
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.endswith('.html'):
                continue
            with open(os.path.join(dirpath, f), encoding='utf-8') as fp:
                m = re.search(r'post-id:(\d+)', fp.readline())
                if m:
                    ids.add(m.group(1))
    return ids


def fetch_all(service, label):
    posts, token = [], None
    while True:
        kw = dict(blogId=BLOG_ID, labels=label, maxResults=50, fetchBodies=True)
        if token:
            kw['pageToken'] = token
        res = service.posts().list(**kw).execute()
        posts.extend(res.get('items', []))
        token = res.get('nextPageToken')
        if not token:
            break
    posts.sort(key=lambda p: p['published'])
    return posts


def archive_label(service, label, root, monthly):
    os.makedirs(root, exist_ok=True)
    existing_ids = collect_existing_ids(root)
    posts = fetch_all(service, label)
    new_count = 0
    for p in posts:
        if p['id'] in existing_ids:
            continue
        date = p['published'][:10]
        out_dir = os.path.join(root, date[:7]) if monthly else root
        os.makedirs(out_dir, exist_ok=True)
        fname = f"{date.replace('-', '')}_{sanitize(p['title'])}.html"
        header = (
            f"<!-- post-id:{p['id']} | published:{p['published']} | "
            f"url:{p['url']} -->\n<!-- title: {p['title']} -->\n"
        )
        with open(os.path.join(out_dir, fname), 'w', encoding='utf-8') as fp:
            fp.write(header + p['content'])
        new_count += 1
    print(f"[{label}] 총 {len(posts)}편 / 신규 {new_count}편 / 건너뜀 {len(posts) - new_count}편")


if __name__ == '__main__':
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)
    for label, (root, monthly) in LABEL_MAP.items():
        archive_label(service, label, root, monthly)
    print("\n아카이브 완료")
