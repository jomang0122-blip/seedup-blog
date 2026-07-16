# -*- coding: utf-8 -*-
"""Search Console API 인증. 기존 auth.py(Blogger 발행용)와 별도 token 파일을 사용해
자동발행 파이프라인의 GOOGLE_TOKEN_JSON Secret에 영향을 주지 않는다."""
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/webmasters']
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CREDENTIALS_FILE = os.path.join(REPO_ROOT, 'credentials.json')
TOKEN_FILE = os.path.join(REPO_ROOT, 'gsc_token.json')


def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())

    return creds


def get_service():
    return build('searchconsole', 'v1', credentials=get_credentials())


if __name__ == '__main__':
    print("브라우저가 열립니다. jomang0122@gmail.com 계정으로 로그인 후 허용을 눌러주세요.")
    creds = get_credentials()
    print("인증 완료! gsc_token.json 저장됨")
    service = get_service()
    sites = service.sites().list().execute()
    print("\n접근 가능한 Search Console 속성:")
    for s in sites.get('siteEntry', []):
        print(f"  {s['siteUrl']}  (권한: {s['permissionLevel']})")
