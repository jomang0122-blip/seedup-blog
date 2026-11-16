# -*- coding: utf-8 -*-
"""글 본문에 통째로 넣은 그림(data:image)을 저장소 파일로 꺼내고, 본문을 그림 주소로 바꾼다.

왜: 그림을 본문에 넣은 글은 100~350KB라, 블로거가 홈·목록 화면에 글을 1~5개만 보여 준다(2026-11-16 확인).
사용:
  python tools/externalize_images.py extract <글ID ...>  → assets/img/{글ID}_{n}.png 저장 + _out/externalize_plan.json
  (그림 파일 push 후)
  python tools/externalize_images.py patch    → plan의 글 본문만 교체(posts.patch, 검색 설명 유지)
"""
import base64, hashlib, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from googleapiclient.discovery import build
from shared.blog_publisher import get_credentials, BLOG_ID

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "assets" / "img"
PLAN = ROOT / "tools" / "_out" / "externalize_plan.json"
CDN = "https://cdn.jsdelivr.net/gh/jomang0122-blip/seedup-blog@main/assets/img/"
DATA = re.compile(r'data:image/png;base64,([A-Za-z0-9+/=]+)')


def svc():
    return build("blogger", "v3", credentials=get_credentials())


def extract(ids):
    s = svc(); IMG.mkdir(parents=True, exist_ok=True)
    plan = json.loads(PLAN.read_text(encoding="utf-8")) if PLAN.exists() else {}
    for pid in ids:
        p = s.posts().get(blogId=BLOG_ID, postId=pid, view="ADMIN").execute()
        files = []
        for n, m in enumerate(DATA.finditer(p["content"]), 1):
            raw = base64.b64decode(m.group(1))
            name = f"{pid}_{n}.png"
            (IMG / name).write_bytes(raw)
            files.append({"name": name, "sha1": hashlib.sha1(raw).hexdigest(), "kb": len(raw) // 1024})
        plan[pid] = {"title": p["title"], "status": p["status"], "before_kb": len(p["content"]) // 1024, "files": files}
        print(pid, p["status"], len(files), "장", p["title"][:40])
    PLAN.parent.mkdir(exist_ok=True)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


def patch(only=None):
    import urllib.request
    s = svc(); plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for pid, info in plan.items():
        if only and pid not in only or info.get("done"):
            continue
        for f in info["files"]:  # 주소가 실제로 열리고 같은 그림인지 먼저 확인
            raw = urllib.request.urlopen(CDN + f["name"], timeout=60).read()
            assert hashlib.sha1(raw).hexdigest() == f["sha1"], f["name"]
        p = s.posts().get(blogId=BLOG_ID, postId=pid, view="ADMIN").execute()
        it = iter(info["files"])
        new = DATA.sub(lambda m: CDN + next(it)["name"], p["content"])
        assert "data:image" not in new
        s.posts().patch(blogId=BLOG_ID, postId=pid, body={"content": new}).execute()
        g = s.posts().get(blogId=BLOG_ID, postId=pid, view="ADMIN").execute()
        info.update(done=True, after_kb=len(g["content"]) // 1024, status_after=g["status"], published=g.get("published"))
        print(pid, info["before_kb"], "→", info["after_kb"], "KB", g["status"], g.get("published"), info["title"][:36])
        PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "extract":
        extract(sys.argv[2:])
    else:
        patch(set(sys.argv[2:]) or None)
