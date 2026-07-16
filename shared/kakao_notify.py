# -*- coding: utf-8 -*-
"""GitHub Actions 발행 실패 시 카카오톡 '나에게 보내기'로 알림 발송.

로컬 실행 시에는 KAKAO_* 환경변수가 없으면 조용히 스킵한다(알림 미설정 상태에서도
기존 job 실행에 영향 없게). refresh_token은 카카오 정책상 매 요청마다 새 access_token
발급에만 쓰이고, 자체는 소비되지 않는다(Blogger의 OAuth 토큰 갱신과 동일 패턴).
"""
import json
import os
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


def notify_failure(job_name: str, run_url: str = "") -> bool:
    """발행 실패 알림 발송. 환경변수 미설정 시 False 반환(스킵), 성공 시 True.

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

        text = f"⚠️ SeedUP 블로그 발행 실패\n\njob: {job_name}"
        if run_url:
            text += f"\n\n로그 확인: {run_url}"

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
    notify_failure("kakao_notify.py 단독 실행 테스트", "")
