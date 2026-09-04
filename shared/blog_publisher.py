# -*- coding: utf-8 -*-
import os
import re
import time
import yaml
from shared.auth import get_credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_FILE = os.path.join(REPO_ROOT, 'config.yaml')

with open(CONFIG_FILE, encoding='utf-8') as f:
    CONFIG = yaml.safe_load(f)

BLOG_ID = CONFIG['blogger']['blog_id']


def _strip_code_fences(text: str) -> str:
    """AI 응답에 포함된 ```html ... ``` 마크다운 코드 블록 기호 제거"""
    text = re.sub(r'```[a-zA-Z]*\n?', '', text)
    text = re.sub(r'\n?```', '', text)
    return text.strip()


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


def update_post(post_id: str, title: str, content: str, labels: list = None) -> dict:
    """기존 Blogger 글 내용 교체 (동일 URL 유지, 중복 글 생성 없음)."""
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)

    body = {
        'title': _strip_code_fences(title),
        'content': _strip_code_fences(content),
        'labels': labels or [],
    }

    post = service.posts().update(
        blogId=BLOG_ID,
        postId=post_id,
        body=body,
    ).execute()

    return {
        'id': post['id'],
        'url': post.get('url', ''),
        'title': post['title'],
    }


def get_recent_posts_by_label(label: str, max_results: int = 3) -> list:
    """특정 라벨이 붙은 최근 포스트 목록 반환. [{title, url, published}]

    orderBy는 'PUBLISHED'/'UPDATED'만 허용(소문자 'published'는 TypeError, 2026-07-06 실측).
    """
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)
    result = service.posts().list(
        blogId=BLOG_ID,
        labels=label,
        maxResults=max_results,
        orderBy='PUBLISHED',
        fetchBodies=False,
        fetchImages=False,
    ).execute()
    posts = []
    for item in result.get('items', []):
        posts.append({
            'title':     item.get('title', ''),
            'url':       item.get('url', ''),
            'published': item.get('published', ''),
        })
    return posts


# 구글 서버측 일시 오류 — 잠시 뒤 같은 요청을 다시 보내면 대개 성공한다.
# 400(잘못된 본문)·401/403(인증)·404는 재시도해도 결과가 같으므로 제외한다.
_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
_PUBLISH_ATTEMPTS = 3
_PUBLISH_BACKOFF = 4.0


def _find_post_by_title(service, title: str, max_results: int = 10):
    """최근 글 중 제목이 정확히 같은 글을 반환. 없거나 조회 실패면 None.

    발행 재시도 직전에 "앞선 요청이 서버에는 반영됐는데 응답만 실패한" 경우를
    가려내 중복 발행을 막는 용도다."""
    try:
        result = service.posts().list(
            blogId=BLOG_ID,
            maxResults=max_results,
            orderBy='PUBLISHED',
            fetchBodies=False,
            fetchImages=False,
        ).execute()
    except Exception:
        return None
    for item in result.get('items', []):
        if item.get('title') == title:
            return item
    return None


def publish_post(title: str, content: str, labels: list = None, status: str = 'LIVE') -> dict:
    """Blogger에 글 발행. status: 'LIVE' 또는 'DRAFT'

    구글 서버 일시 오류(5xx·429)는 백오프 후 재시도한다 — AI 생성·검증을 모두
    마친 뒤 마지막 발행 단계에서 죽으면 그 생성 크레딧이 통째로 날아가기 때문이다
    (2026-09-04 kr_daily 실사고: Blogger 503 backendError 한 번에 검증까지 통과한
    12,287자가 폐기됨). 재시도 전에는 같은 제목 글이 이미 등록됐는지 확인해
    중복 발행을 막는다."""
    creds = get_credentials()
    service = build('blogger', 'v3', credentials=creds)

    clean_title = _strip_code_fences(title)
    body = {
        'title': clean_title,
        'content': _strip_code_fences(content),
        'labels': labels or [],
    }

    post = None
    for attempt in range(_PUBLISH_ATTEMPTS):
        try:
            post = service.posts().insert(
                blogId=BLOG_ID,
                body=body,
                isDraft=(status == 'DRAFT'),
            ).execute()
            break
        except HttpError as e:
            http_status = getattr(getattr(e, 'resp', None), 'status', None)
            if http_status not in _RETRYABLE_HTTP_STATUS or attempt == _PUBLISH_ATTEMPTS - 1:
                raise
            existing = _find_post_by_title(service, clean_title)
            if existing:
                print(f"  [발행 재시도] 직전 요청이 실제로는 등록됨 — 중복 발행 생략")
                post = existing
                break
            wait = _PUBLISH_BACKOFF * (attempt + 1)
            print(f"  [발행 재시도 {attempt + 1}/{_PUBLISH_ATTEMPTS - 1}] "
                  f"Blogger 일시 오류 {http_status} — {wait:.0f}초 후 재시도")
            time.sleep(wait)

    return {
        'id': post['id'],
        'url': post.get('url', ''),
        'title': post['title'],
    }
