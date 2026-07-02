# -*- coding: utf-8 -*-
import os
import yaml
from auth import get_credentials
from googleapiclient.discovery import build


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.yaml')

with open(CONFIG_FILE, encoding='utf-8') as f:
    CONFIG = yaml.safe_load(f)

BLOG_ID = CONFIG['blogger']['blog_id']


def check_today_post(date_str: str) -> dict | None:
    """당일 이미 발행된 포스트가 있으면 {'id', 'url'} 반환, 없으면 None (KST 기준)"""
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)
    start = f"{date_str}T00:00:00+09:00"
    end   = f"{date_str}T23:59:59+09:00"
    result = service.posts().list(
        blogId=BLOG_ID,
        startDate=start,
        endDate=end,
        fetchBodies=False,
        fetchImages=False,
        maxResults=5,
    ).execute()
    items = result.get("items", [])
    if items:
        return {"id": items[0]["id"], "url": items[0].get("url", "")}
    return None


def publish_post(title: str, content: str, labels: list = None, status: str = 'LIVE') -> dict:
    """
    Blogger에 글 발행
    status: 'LIVE'(즉시 발행) 또는 'DRAFT'(임시저장)
    반환: {'id': ..., 'url': ...}
    """
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)

    body = {
        'title': title,
        'content': content,
        'labels': labels or [],
    }

    post = service.posts().insert(
        blogId=BLOG_ID,
        body=body,
        isDraft=(status == 'DRAFT'),
    ).execute()

    return {
        'id': post['id'],
        'url': post.get('url', ''),
        'title': post['title'],
    }


if __name__ == '__main__':
    # 테스트 발행
    result = publish_post(
        title='[테스트] SeedUP 블로그 자동 발행 시스템 연동 확인',
        content='''<p>이 글은 Python Blogger API 연동 테스트 포스팅입니다.</p>
<p>SeedUP 블로그 자동 발행 시스템이 정상적으로 작동하면 이 글이 블로그에 업로드됩니다.</p>
<p>확인 후 삭제해도 됩니다.</p>''',
        labels=['테스트'],
        status='LIVE',
    )
    print(f"발행 완료!")
    print(f"  제목: {result['title']}")
    print(f"  URL : {result['url']}")
