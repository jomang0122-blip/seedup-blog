# -*- coding: utf-8 -*-
"""
시드업 클래스 — 레벨별 HTML 배너 카드 + 핵심 박스 생성
"""

LEVEL_CONFIG = {
    "초급": {"color": "#27ae60", "bg": "#eafaf1", "badge": "초급 BASIC",         "icon": "🌱"},
    "중급": {"color": "#3182f6", "bg": "#eef4ff", "badge": "중급 INTERMEDIATE",  "icon": "📈"},
    "고급": {"color": "#e74c3c", "bg": "#fef2f2", "badge": "고급 ADVANCED",      "icon": "🔥"},
}


def generate_banner_card(level: str, category: str, title: str, episode: int) -> str:
    cfg   = LEVEL_CONFIG.get(level, LEVEL_CONFIG["초급"])
    color = cfg["color"]
    bg    = cfg["bg"]
    badge = cfg["badge"]
    icon  = cfg["icon"]
    return (
        f'<div style="background:{bg};border-left:6px solid {color};border-radius:12px;'
        f'padding:24px 28px;margin:0 0 28px 0;font-family:-apple-system,\'Malgun Gothic\',\'Noto Sans KR\',sans-serif;'
        f'box-shadow:0 2px 8px rgba(0,0,0,0.07);">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
        f'<span style="background:{color};color:#fff;font-size:11px;font-weight:700;'
        f'letter-spacing:0.08em;padding:4px 12px;border-radius:20px;">{badge}</span>'
        f'<span style="color:#999;font-size:12px;">EP.{episode:02d}</span>'
        f'</div>'
        f'<p style="color:{color};font-size:13px;font-weight:600;margin:0 0 6px 0;">{icon} {category}</p>'
        f'<p style="color:#1a1a1a;font-size:22px;font-weight:800;line-height:1.35;margin:0 0 14px 0;">{title}</p>'
        f'<div style="border-top:1px solid {color}33;padding-top:12px;display:flex;align-items:center;gap:8px;">'
        f'<span style="background:{color};color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;">시드업 클래스</span>'
        f'<span style="color:#888;font-size:12px;">SeedUP INVEST 주식 교육 시리즈</span>'
        f'</div></div>'
    )


def generate_key3_box(level: str, items: list) -> str:
    cfg   = LEVEL_CONFIG.get(level, LEVEL_CONFIG["초급"])
    color = cfg["color"]
    bg    = cfg["bg"]
    li_html = ""
    for i, item in enumerate(items[:3]):
        li_html += (
            f'<li style="padding:10px 14px;margin-bottom:8px;background:#fff;border-radius:8px;'
            f'border-left:4px solid {color};font-size:15px;line-height:1.5;color:#2c2c2c;list-style:none;">'
            f'<span style="color:{color};font-weight:700;margin-right:6px;">{i+1}.</span>{item}</li>'
        )
    return (
        f'<div style="background:{bg};border:1.5px solid {color}55;border-radius:12px;'
        f'padding:20px 22px;margin:20px 0 28px 0;">'
        f'<p style="font-size:13px;font-weight:700;color:{color};margin:0 0 14px 0;letter-spacing:0.04em;">✅ 오늘의 핵심 3가지</p>'
        f'<ol style="list-style:none;margin:0;padding:0;">{li_html}</ol>'
        f'</div>'
    )
