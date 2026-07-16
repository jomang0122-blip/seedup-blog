# -*- coding: utf-8 -*-
"""SeedUP INVEST Search Console 리포트 CLI. 마케팅팀이 검색성과·색인상태를 조회할 때 사용.

사용 예:
    python tools/gsc_report.py sites
    python tools/gsc_report.py sitemaps
    python tools/gsc_report.py performance --start 2026-06-25 --end 2026-07-08
    python tools/gsc_report.py inspect https://www.seedup-invest.com/2026/07/example.html
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from shared.gsc_auth import get_service

# 확인 필요: GSC에 등록된 실제 속성 식별자로 교체할 것 (도메인 속성이면 'sc-domain:seedup-invest.com' 형태일 수 있음)
SITE_URL = 'https://www.seedup-invest.com/'


def list_sites():
    service = get_service()
    result = service.sites().list().execute()
    for s in result.get('siteEntry', []):
        print(f"{s['siteUrl']}  (권한: {s['permissionLevel']})")


def list_sitemaps(site_url):
    service = get_service()
    result = service.sitemaps().list(siteUrl=site_url).execute()
    sitemaps = result.get('sitemap', [])
    if not sitemaps:
        print("등록된 사이트맵 없음")
        return
    for sm in sitemaps:
        print(f"{sm['path']}")
        print(f"  마지막 제출: {sm.get('lastSubmitted', '-')} / 마지막 다운로드: {sm.get('lastDownloaded', '-')}")
        for c in sm.get('contents', []):
            print(f"  {c['type']}: 제출 {c['submitted']}건 / 색인 {c.get('indexed', '확인 필요')}건")


def search_performance(site_url, start_date, end_date, dimension='query', row_limit=20):
    service = get_service()
    body = {
        'startDate': start_date,
        'endDate': end_date,
        'dimensions': [dimension],
        'rowLimit': row_limit,
    }
    result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows = result.get('rows', [])
    if not rows:
        print("해당 기간 데이터 없음 (아직 색인/노출이 발생하지 않았을 수 있음)")
        return
    print(f"{'키워드/페이지':<40} {'클릭':>6} {'노출':>8} {'CTR':>7} {'평균순위':>8}")
    for r in rows:
        key = r['keys'][0]
        print(f"{key:<40} {r['clicks']:>6} {r['impressions']:>8} {r['ctr']*100:>6.1f}% {r['position']:>8.1f}")


def inspect_url(url, site_url):
    service = get_service()
    body = {'inspectionUrl': url, 'siteUrl': site_url}
    result = service.urlInspection().index().inspect(body=body).execute()
    status = result['inspectionResult']['indexStatusResult']
    print(f"색인 상태: {status.get('coverageState', '-')}")
    print(f"마지막 크롤링: {status.get('lastCrawlTime', '확인 필요 — 아직 크롤링 안 됐을 수 있음')}")
    print(f"robots.txt 허용 여부: {status.get('robotsTxtState', '-')}")
    print(f"색인 등록된 URL: {status.get('googleCanonical', '-')}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SeedUP Search Console 리포트')
    sub = parser.add_subparsers(dest='cmd', required=True)

    sub.add_parser('sites')
    sub.add_parser('sitemaps')

    p_perf = sub.add_parser('performance')
    p_perf.add_argument('--start', required=True, help='YYYY-MM-DD')
    p_perf.add_argument('--end', required=True, help='YYYY-MM-DD')
    p_perf.add_argument('--dimension', default='query', choices=['query', 'page', 'date', 'device', 'country'])
    p_perf.add_argument('--limit', type=int, default=20)

    p_url = sub.add_parser('inspect')
    p_url.add_argument('url')

    args = parser.parse_args()

    if args.cmd == 'sites':
        list_sites()
    elif args.cmd == 'sitemaps':
        list_sitemaps(SITE_URL)
    elif args.cmd == 'performance':
        search_performance(SITE_URL, args.start, args.end, args.dimension, args.limit)
    elif args.cmd == 'inspect':
        inspect_url(args.url, SITE_URL)
