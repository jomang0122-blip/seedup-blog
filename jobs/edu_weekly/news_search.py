# -*- coding: utf-8 -*-
"""
시드업 클래스 — 주제별 최신 뉴스 검색 (Naver 검색 API)
"""
import os
import re
import requests


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
        print(f"  [뉴스검색] '{query}' → {len(titles)}건")
        return titles
    except Exception as e:
        print(f"  [뉴스검색] '{query}' 실패: {e}")
        return []
