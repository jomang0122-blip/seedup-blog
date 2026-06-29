# -*- coding: utf-8 -*-
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/blogger']
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CREDENTIALS_FILE = os.path.join(REPO_ROOT, 'credentials.json')
TOKEN_FILE = os.path.join(REPO_ROOT, 'token.json')
BLOG_URL = 'https://seedup-invest.blogspot.com/'


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


if __name__ == '__main__':
    print("브라우저가 열립니다. jomang0122@gmail.com 계정으로 로그인 후 허용을 눌러주세요.")
    creds = get_credentials()
    print("인증 완료! token.json 저장됨")
    service = build('blogger', 'v3', credentials=creds)
    blog = service.blogs().getByUrl(url=BLOG_URL).execute()
    print(f"블로그 ID: {blog['id']}")
