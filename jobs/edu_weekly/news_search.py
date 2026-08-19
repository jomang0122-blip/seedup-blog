# -*- coding: utf-8 -*-
"""
시드업 클래스 — 주제별 최신 뉴스 검색 (Naver 검색 API)
"""
import os
import re
import requests

# 시드업 클래스는 국내 주식 교육 콘텐츠 — 태그 키워드만으로 검색하면 검색 결과에
# 가상자산(코인) 뉴스가 섞여 들어올 수 있어(2026-08-18 확인), 제목에 이 키워드가
# 포함된 기사는 결과에서 제외한다.
_EXCLUDE_KEYWORDS = [
    "비트코인", "이더리움", "코인", "가상자산", "암호화폐", "리플", "도지코인", "NFT",
]


def search_topic_news(tags: list, display: int = 5) -> list:
    """태그 키워드로 Naver 뉴스 검색. 최신 뉴스 제목 리스트 반환.
    API 키 미설정 또는 오류 시 빈 리스트 반환 (폴백 안전).
    """
    client_id     = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []

    query = " ".join(tags[:3])
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": query, "display": display, "sort": "date"},
            timeout=5,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        titles = [re.sub(r"<[^>]+>", "", item["title"]) for item in items]
        before = len(titles)
        titles = [t for t in titles if not any(kw in t for kw in _EXCLUDE_KEYWORDS)]
        if len(titles) < before:
            print(f"  [뉴스검색] 가상자산 관련 {before - len(titles)}건 제외")
        print(f"  [뉴스검색] '{query}' → {len(titles)}건")
        return titles
    except Exception as e:
        print(f"  [뉴스검색] '{query}' 실패: {e}")
        return []
