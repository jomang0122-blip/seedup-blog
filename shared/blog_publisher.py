# -*- coding: utf-8 -*-
import os
import yaml
from shared.auth import get_credentials
from googleapiclient.discovery import build

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_FILE = os.path.join(REPO_ROOT, 'config.yaml')

with open(CONFIG_FILE, encoding='utf-8') as f:
    CONFIG = yaml.safe_load(f)

BLOG_ID = CONFIG['blogger']['blog_id']


def check_today_post(date_str: str, label_filter: str = None) -> dict | None:
    """당일 이미 발행된 포스트가 있으면 {'id', 'url'} 반환, 없으면 None.
    date_str: YYYY-MM-DD 형식
    label_filter: 제목 포함 문자열로 특정 타입만 필터 (예: '미증시', '위클리')
    """
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)
    start = f"{date_str}T00:00:00+09:00"
    end = f"{date_str}T23:59:59+09:00"
    result = service.posts().list(
        blogId=BLOG_ID,
        startDate=start,
        endDate=end,
        fetchBodies=False,
        fetchImages=False,
        maxResults=10,
    ).execute()
    items = result.get("items", [])
    for item in items:
        title = item.get("title", "")
        if label_filter is None or label_filter in title:
            return {"id": item["id"], "url": item.get("url", "")}
    return None


def publish_post(title: str, content: str, labels: list = None, status: str = 'LIVE') -> dict:
    """Blogger에 글 발행. status: 'LIVE' 또는 'DRAFT'"""
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
