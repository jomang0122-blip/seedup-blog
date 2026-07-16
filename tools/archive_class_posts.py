# -*- coding: utf-8 -*-
"""시드업 클래스 발행글 로컬 아카이브 스크립트.

Blogger에서 "주식투자클래스" 라벨 글을 전부 내려받아
04_시드업클래스/01_발행글/ 에 저장하고, edu_topics.json을 읽어
00_주제관리/커리큘럼.md 를 갱신한다. 이미 받은 글은 건너뛴다(증분).

실행:
    cd auto_publisher
    ./.venv/Scripts/python.exe tools/archive_class_posts.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from shared.auth import get_credentials
from googleapiclient.discovery import build

BLOG_ID = '2047573422787647052'
LABEL = '주식투자클래스'
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CLASS_ROOT = os.path.abspath(os.path.join(REPO_ROOT, '..', '..', '04_시드업클래스'))
POSTS_DIR = os.path.join(CLASS_ROOT, '01_발행글')
CURRICULUM = os.path.join(CLASS_ROOT, '00_주제관리', '커리큘럼.md')
TOPICS_JSON = os.path.join(REPO_ROOT, 'data', 'edu_topics.json')


def sanitize(title: str) -> str:
    """파일명용: 레벨 태그 제거, 부제 절삭, Windows 금지문자 제거."""
    t = re.sub(r'^\[[^\]]+\]\s*', '', title)
    t = t.split(' — ')[0].split(' - ')[0]
    t = re.sub(r'[\\/:*?"<>|]', '', t)
    return t.replace(' ', '').strip()[:40]


def fetch_all_class_posts(service):
    posts, token = [], None
    while True:
        kw = dict(blogId=BLOG_ID, labels=LABEL, maxResults=50, fetchBodies=True)
        if token:
            kw['pageToken'] = token
        res = service.posts().list(**kw).execute()
        posts.extend(res.get('items', []))
        token = res.get('nextPageToken')
        if not token:
            break
    posts.sort(key=lambda p: p['published'])
    return posts


def archive_posts(service):
    os.makedirs(POSTS_DIR, exist_ok=True)
    existing = {f for f in os.listdir(POSTS_DIR) if f.endswith('.html')}
    # 기존 파일의 post id 목록 (파일 첫 줄 주석에 기록해둠)
    existing_ids = set()
    for f in existing:
        with open(os.path.join(POSTS_DIR, f), encoding='utf-8') as fp:
            first = fp.readline()
            m = re.search(r'post-id:(\d+)', first)
            if m:
                existing_ids.add(m.group(1))

    posts = fetch_all_class_posts(service)
    new_count = 0
    for seq, p in enumerate(posts, start=1):
        if p['id'] in existing_ids:
            continue
        date = p['published'][:10].replace('-', '')
        fname = f"{seq:03d}_{date}_{sanitize(p['title'])}.html"
        header = (
            f"<!-- post-id:{p['id']} | published:{p['published']} | "
            f"url:{p['url']} -->\n<!-- title: {p['title']} -->\n"
        )
        with open(os.path.join(POSTS_DIR, fname), 'w', encoding='utf-8') as fp:
            fp.write(header + p['content'])
        print(f"저장: {fname}")
        new_count += 1
    print(f"\n발행글 총 {len(posts)}편 / 신규 저장 {new_count}편 / 기존 {len(posts) - new_count}편 건너뜀")
    return posts


def build_curriculum():
    d = json.load(open(TOPICS_JSON, encoding='utf-8'))
    topics = d['topics']
    done = [t for t in topics if t.get('published')]
    lines = [
        "# 시드업 클래스 커리큘럼 현황",
        "",
        f"> 자동 생성: tools/archive_class_posts.py 실행 시 갱신 (원본: auto_publisher/data/edu_topics.json)",
        "",
        f"전체 {len(topics)}개 주제 / 발행완료 {len(done)}개 / 남은 주제 {len(topics) - len(done)}개",
        "",
        "| ID | 상태 | 레벨 | 분류 | 제목 | 발행일 |",
        "|---|---|---|---|---|---|",
    ]
    for t in topics:
        status = "✅" if t.get('published') else "⬜"
        pub = (t.get('published_at') or '')[:10]
        lines.append(f"| {t['id']} | {status} | {t['level']} | {t['category']} | {t['title']} | {pub} |")
    os.makedirs(os.path.dirname(CURRICULUM), exist_ok=True)
    with open(CURRICULUM, 'w', encoding='utf-8') as fp:
        fp.write("\n".join(lines) + "\n")
    print(f"커리큘럼 갱신: {CURRICULUM}")


if __name__ == '__main__':
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)
    archive_posts(service)
    build_curriculum()
