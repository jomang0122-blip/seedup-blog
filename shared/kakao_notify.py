# -*- coding: utf-8 -*-
"""GitHub Actions 발행 실패 시 카카오톡 '나에게 보내기'로 알림 발송.

로컬 실행 시에는 KAKAO_* 환경변수가 없으면 조용히 스킵한다(알림 미설정 상태에서도
기존 job 실행에 영향 없게). refresh_token은 카카오 정책상 매 요청마다 새 access_token
발급에만 쓰이고, 자체는 소비되지 않는다(Blogger의 OAuth 토큰 갱신과 동일 패턴).
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


def _refresh_access_token(rest_api_key: str, client_secret: str, refresh_token: str) -> str:
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request("https://kauth.kakao.com/oauth/token", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    return resp["access_token"]


# ── 실패 사유 추출 ──────────────────────────────────────────────────
# 발행 스텝의 출력을 tee로 남긴 로그에서 "왜 죽었는지" 한 줄을 뽑는다.
# 알림에 job 이름만 있으면 결국 Actions 로그를 열어야 원인을 알 수 있어서,
# 실패를 알아채고도 대응이 늦어진다(2026-09-07 미증시 휴장 안내 실패는
# 하루 뒤 총괄이 발견함).
_ERR_APP = re.compile(r"^\s*\[오류\]\s*(.+)$")                        # main.py가 직접 찍는 요약
_ERR_EXC = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception)\b.*)$")  # 트레이스백 마지막 줄


def extract_reason(log_path: str, max_chars: int = 300) -> str:
    """발행 로그에서 실패 사유 한 줄을 반환. 못 찾으면 빈 문자열.

    우선순위: main.py의 [오류] 요약 → 예외 클래스 줄 → 마지막 출력 줄.
    [오류]는 코드가 의도적으로 남긴 한글 요약이라 가장 읽기 좋고,
    안 잡힌 예외로 죽은 경우에는 트레이스백 마지막 줄이 원인이다.
    """
    if not log_path:
        return ""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return ""
    if not lines:
        return ""
    for pat in (_ERR_APP, _ERR_EXC):
        hits = [m.group(1) for m in (pat.match(ln) for ln in lines) if m]
        if hits:
            return hits[-1][:max_chars]
    return lines[-1][:max_chars]


# 카카오 기본 text 템플릿의 text 상한(문서상 200자 — 여유를 두고 190자로 자른다).
# 사유가 길다는 이유로 전송 자체가 실패하면 원인은커녕 실패 사실도 못 알게 된다.
_MAX_TEXT = 190


def _shorten(s: str, room: int) -> str:
    """가운데를 잘라 앞뒤를 남긴다.

    에러 문구는 앞(예외 종류)과 뒤(구체적인 값)가 둘 다 중요하다.
    뒤만 자르면 정작 원인인 값이 사라진다
    (예: "...한글 표기 필요: ['amp']"에서 ['amp']가 없으면 알 수 없다).
    """
    if len(s) <= room:
        return s
    if room <= 1:
        return s[:max(room, 0)]
    keep = room - 1
    front = keep * 3 // 5
    return s[:front] + "…" + s[len(s) - (keep - front):]


def _build_text(job_name: str, run_url: str, reason: str) -> str:
    """상한을 넘지 않는 선에서 사유까지 담은 알림 문구를 만든다."""
    head = "⚠️ SeedUP 블로그 발행 실패\n\njob: " + job_name
    tail = ("\n\n로그 확인: " + run_url) if run_url else ""
    budget = _MAX_TEXT - len(head) - len(tail)
    if reason:
        room = budget - len("\n사유: ")
        mid = ("\n사유: " + _shorten(reason, room)) if room > 0 else ""
    else:
        # 발행 스텝 로그가 없다 = 발행 이전/이후 스텝에서 죽었다는 뜻
        mid = "\n단계: 발행 스텝 밖 (로그 확인 필요)"
        if len(mid) > budget:
            mid = ""
    return head + mid + tail


def notify_failure(job_name: str, run_url: str = "", reason: str = "") -> bool:
    """발행 실패 알림 발송. 환경변수 미설정 시 False 반환(스킵), 성공 시 True.

    reason: 실패 사유 한 줄. extract_reason()으로 발행 로그에서 뽑아 넘긴다.
            비어 있으면 발행 스텝 밖에서 죽었다는 뜻이라 그렇게 표기한다.

    사용 환경변수: KAKAO_REST_API_KEY, KAKAO_CLIENT_SECRET, KAKAO_REFRESH_TOKEN
    """
    rest_api_key = os.getenv("KAKAO_REST_API_KEY")
    client_secret = os.getenv("KAKAO_CLIENT_SECRET")
    refresh_token = os.getenv("KAKAO_REFRESH_TOKEN")

    if not (rest_api_key and client_secret and refresh_token):
        print("  [카카오 알림] 환경변수 미설정 — 알림 발송 생략")
        return False

    try:
        access_token = _refresh_access_token(rest_api_key, client_secret, refresh_token)

        text = _build_text(job_name, run_url, reason)

        template = {
            "object_type": "text",
            "text": text,
            "link": {
                "web_url": run_url or "https://www.seedup-invest.com/",
                "mobile_web_url": run_url or "https://www.seedup-invest.com/",
            },
        }
        data = urllib.parse.urlencode({"template_object": json.dumps(template, ensure_ascii=False)}).encode()
        req = urllib.request.Request(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            data=data, method="POST",
        )
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
        with urllib.request.urlopen(req, timeout=15) as r:
            json.loads(r.read())
        print(f"  [카카오 알림] 발송 완료: {job_name}")
        return True
    except Exception as e:
        print(f"  [카카오 알림] 발송 실패(무시하고 계속): {e}")
        return False


if __name__ == "__main__":
    notify_failure("kakao_notify.py 단독 실행 테스트", "", "테스트 사유")
