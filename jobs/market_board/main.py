# -*- coding: utf-8 -*-
"""시장 현황판 — 블로거 고정 페이지 갱신 (API 크레딧 0: Anthropic 호출 없음).

실행 (cd auto_publisher, PYTHONPATH=.)
  python jobs/market_board/main.py --part daily   국내 데일리 직후: 매일 칸 자료(board_daily.json) 갱신 → 페이지 다시 그림
  python jobs/market_board/main.py --part lab     평일 아침: 랩 지표 25개(board_lab.json·이력 CSV) 갱신 → 페이지 다시 그림
  python jobs/market_board/main.py --part none    자료는 그대로, 저장된 두 파일로 페이지만 다시 그림
  기본은 미리보기만(tools/_out/market_board_preview.html). 블로거에 반영하려면 --publish.
  페이지가 아직 없으면 --publish가 **비공개 초안**으로 만들고 id를 data/board/page.json에 남긴다.
  공개 전환은 블로거 관리 화면에서 한다(이 코드는 공개/초안 상태를 바꾸지 않는다).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
import page as P   # noqa: E402

DATA = REPO / "data" / "board"
PAGE_TITLE = "시장 현황판"
PREVIEW = REPO / "tools" / "_out" / "market_board_preview.html"


def load(name):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["daily", "lab", "none"], required=True)
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()

    if a.part == "daily":
        import daily as DL
        d = DL.collect()
        (DATA / "board_daily.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"[매일 칸] {d['asof']} · 시장 내부 체력 {d['breadth_date']} · 업종 {d['n_sectors']} · 시총 {len(d['mcap'])}")
    elif a.part == "lab":
        import compute as CP
        payload, _, _ = CP.run(save=True)
        if payload["meta"]["fails"]:
            print(f"[랩 칸] 실패 항목 {len(payload['meta']['fails'])}개 — 이전 값으로 표시")

    lab, daily = load("board_lab.json"), load("board_daily.json")
    latest = None
    if a.publish:
        try:
            from shared.blog_publisher import get_recent_posts_by_label
            r = get_recent_posts_by_label("국내데일리", 1)
            latest = r[0]["url"] if r else None
        except Exception as e:
            print(f"  최신 데일리 글 주소 조회 실패(라벨 모음 링크로 대체): {e}")
    html = P.render(lab, daily, latest)

    from shared.utils import find_kanji
    kj = find_kanji(html)
    if kj:
        raise SystemExit(f"페이지에 한자 {len(kj)}자 {sorted(set(kj))[:10]} — 반영 중단 (CLAUDE.md 한자 금지)")

    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW.write_text('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                       '<meta name="viewport" content="width=device-width,initial-scale=1"><title>시장 현황판 미리보기</title>'
                       '<style>body{margin:0;background:#fff}.wrap{max-width:760px;margin:24px auto;padding:0 16px}</style></head>'
                       f'<body><div class="wrap">{html}</div></body></html>', encoding="utf-8")
    print(f"[페이지] {len(html) / 1024:.0f}KB · 미리보기 {PREVIEW}")

    if not a.publish:
        return
    from shared.blog_publisher import create_page, find_page_by_title, update_page
    info = load("page.json") or find_page_by_title(PAGE_TITLE)
    if info:
        r = update_page(info["id"], PAGE_TITLE, html)
        where = "(초안이라 공개 주소 없음 — 블로거 관리 화면 > 페이지에서 미리보기)" if r["status"] == "DRAFT" else r["url"]
        print(f"[블로거] 페이지 고침 · {r['status']} · {where}")
    else:
        r = create_page(PAGE_TITLE, html, draft=True)
        print(f"[블로거] 새 페이지를 비공개 초안으로 만듦 · id {r['id']}")
    (DATA / "page.json").write_text(json.dumps({"id": r["id"], "title": PAGE_TITLE}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    main()
