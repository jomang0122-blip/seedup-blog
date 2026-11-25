# -*- coding: utf-8 -*-
"""시드업 클래스 '이전 편 / 다음 편' 내부 링크 (2026-11-25 신설).

목적: 클래스 글끼리 서로 이어 구글이 '발견됨-색인 안 됨' 글을 다시 찾게 하고,
검색으로 들어온 방문자(검색 유입 1위가 클래스 초급 글)가 한 편만 보고 나가지 않게 한다.

- 발행 직전: 새 글에 이전 편 링크(apply_nav)
- 발행 직후: 직전 편 본문에 다음 편 링크 추가(link_previous_post) — 본문만 patch(검색 설명 유지)
같은 표지(<!-- class-nav -->) 사이를 통째로 바꾸므로 여러 번 실행해도 상자가 겹치지 않는다.
"""
import re
import time

MARK_S = "<!-- class-nav -->"
MARK_E = "<!-- /class-nav -->"
_BLOCK_RE = re.compile(re.escape(MARK_S) + r".*?" + re.escape(MARK_E) + r"\n?", re.S)


def topic_link(topics: list, topic_id: int):
    """발행된 주제면 (표시 제목, 주소), 아니면 None."""
    t = next((x for x in topics if x.get("id") == topic_id), None)
    if not t or not t.get("published") or not t.get("post_url"):
        return None
    return (f"[{t['level']}] {t['title']}", t["post_url"])


def nav_html(prev, nxt) -> str:
    if not prev and not nxt:
        return ""
    rows = []
    for arrow, item in (("← 이전 편", prev), ("다음 편 →", nxt)):
        if item:
            title, url = item
            rows.append(
                f'<p style="margin:4px 0;font-size:14px;"><span style="color:#8b95a1;">{arrow}</span> '
                f'<a href="{url}" style="color:#3182f6;text-decoration:none;font-weight:600;">{title}</a></p>'
            )
    return (
        MARK_S
        + '<div style="margin:24px 0 0 0;padding:14px 18px;background:#fafbfc;border-radius:8px;'
        'border:1px solid #e5e8eb;font-family:-apple-system,\'Malgun Gothic\',sans-serif;">'
        + "".join(rows) + "</div>" + MARK_E + "\n"
    )


def apply_nav(content: str, prev, nxt) -> str:
    """기존 상자를 지우고, '📚 시드업 클래스 전체 보기' 상자 바로 앞(없으면 면책 문구 앞, 그것도 없으면 끝)에 넣는다."""
    content = _BLOCK_RE.sub("", content)
    block = nav_html(prev, nxt)
    if not block:
        return content
    i = content.find("📚 시드업 클래스 전체 보기")
    if i >= 0:
        i = content.rfind("<div", 0, i)
    if i < 0:
        i = content.find("⚠️ 본 포스트는")
        if i >= 0:
            i = content.rfind("<p", 0, i)
    if i < 0:
        return content + "\n" + block
    return content[:i] + block + content[i:]


def _path_of(url: str) -> str:
    return re.sub(r"^https?://[^/]+", "", url)


def patch_nav(svc, blog_id: str, url: str, prev, nxt, backup_dir=None, tries: int = 3) -> bool:
    """주소로 글을 찾아 본문의 이전·다음 상자만 바꾼다(posts.patch, 검색 설명 유지). 바뀐 게 없으면 False."""
    for k in range(tries):
        try:
            post = svc.posts().getByPath(blogId=blog_id, path=_path_of(url), view="ADMIN").execute()
            new = apply_nav(post["content"], prev, nxt)
            if new == post["content"]:
                return False
            if backup_dir is not None:
                (backup_dir / f"{post['id']}.html").write_text(post["content"], encoding="utf-8")
            svc.posts().patch(blogId=blog_id, postId=post["id"], body={"content": new}).execute()
            return True
        except Exception as e:  # 429 등 일시 오류는 잠시 쉬고 재시도
            if k == tries - 1:
                raise
            print(f"  [이전·다음] 재시도 {k + 1}: {e}")
            time.sleep(10 * (k + 1))
    return False
