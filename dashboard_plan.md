# SeedUP 대시보드 — 에이전트 지침 & 개발 흐름 (제안서)

> 작성일: 2026-08-27 | 브랜치: `claude/youtube-dashboard-agent-analysis-ilcnef`
> 상태: 제안 — 사용자 검토 대기

---

## 0. 먼저: 요청하신 유튜브 영상은 분석하지 못했습니다

이 세션의 아웃바운드 트래픽은 조직 이그레스 프록시를 거치는데, `youtube.com` 이 정책상
차단돼 있습니다(`EGRESS_BLOCKED`, oEmbed 엔드포인트도 CONNECT 403). 검색 인덱스에도
해당 영상 ID(`sozxBiyc3qQ`)에 대한 공개 정보가 없어 제목·채널조차 확인되지 않았습니다.
**영상 내용을 추측해서 쓰지 않았습니다.** 이 문서는 전적으로 이 저장소의 실제 코드·로그·
운영 이력을 실측해 작성한 것입니다.

영상 내용을 반영하려면 아래 중 하나를 주시면 됩니다.
- 유튜브 자막 텍스트를 대화창에 붙여넣기 (가장 정확)
- 영상 제목 + 채널명 (검색으로 2차 자료를 찾아볼 수 있음)
- 영상에서 인상 깊었던 요점 3~5줄 요약

---

## 1. 현황 진단 (2026-08-27 실측)

| 항목 | 실측값 |
|---|---|
| 자동발행 job | 6개 (`kr_daily`, `kr_weekly`, `kr_monthly`, `us_daily`, `us_weekly`, `edu_weekly`) |
| 발행 로그 | 171건 (edu_weekly 73 / us_daily 40 / kr_daily 39 / kr_weekly 8 / us_weekly 8 / kr_monthly 2) |
| 트리거 방식 | 전부 `workflow_dispatch` — 스케줄은 외부(cron-job.org)에 있음 |
| 교육 콘텐츠 재고 | `data/edu_topics.json` 87개 중 61개 발행 → **잔여 26편** |
| 드래프트 큐 | `_approved` 8건 / `_published` 12건 |
| 실패 감지 | `shared/kakao_notify.py` 카카오톡 1회성 알림만 |
| 검색성과 | `tools/gsc_report.py` CLI — 조회만 가능, 축적 없음 |

### 진단에서 드러난 3가지 구조적 결함

**(1) 실패는 기록이 남지 않는다 — 대시보드의 근본 전제가 깨져 있음**
`jobs/kr_daily/main.py:35` 의 `save_log()` 는 **발행에 성공한 뒤에만** 호출됩니다.
데이터 수집 실패, 검증 실패, Blogger API 실패는 전부 `sys.exit(1)` 로 빠지면서
로그 파일 자체가 생성되지 않습니다(`main.py` 내 `sys.exit(1)` 경로만 12곳).
즉 지금 `logs/` 는 "발행 이력"이지 "실행 이력"이 아닙니다.
**이 상태로 대시보드를 만들면 성공률이 항상 100%로 표시됩니다.** 대시보드보다
이 수정이 먼저입니다.

**(2) 로그 스키마가 job마다 다르다**
- 날짜 키: `kr_daily` 는 `date`, 나머지는 `kst_date`
- 지수 키: `kospi_close` / `nasdaq_close` / `kospi_weekly_pct` / `nasdaq_weekly_pct` / `kospi_monthly_pct`
- `search_description` 은 `us_weekly` 20260802 이후부터만 존재
집계 코드가 job별 분기로 뒤덮이게 되므로, 공통 스키마를 먼저 고정해야 합니다.

**(3) 검색성과 데이터가 휘발된다**
Search Console API는 약 16개월 롤링 보관입니다. 지금부터 매일 스냅샷을 커밋해두지
않으면 "2026년 하반기 성장 곡선"은 나중에 어떤 대시보드로도 복원할 수 없습니다.
**이건 대시보드 UI보다 우선순위가 높은 작업입니다.**

---

## 2. 대시보드가 답해야 할 질문 (KPI 5개)

대시보드는 "차트 모음"이 아니라 **정해진 질문에 답하는 도구**로 정의합니다.
아래 5개 외의 지표는 v1에서 넣지 않습니다.

| # | 질문 | 지표 | 데이터 출처 |
|---|---|---|---|
| 1 | 어제 파이프라인이 정상이었나? | job별 최근 실행 상태 / 연속 성공일 / **발행 누락**(예상 발행일에 로그 부재) | `logs/runs.jsonl` (신규) |
| 2 | 콘텐츠 재고가 언제 바닥나나? | 잔여 토픽 26편 ÷ 최근 4주 소진율 → 고갈 예상일 | `data/edu_topics.json` |
| 3 | 품질이 나빠지고 있나? | `validation_issues` 발생률(주간), `char_count` 이상치 | `logs/*.json` |
| 4 | 검색에서 자라고 있나? | 클릭·노출·CTR·평균순위 28일 추이, 색인률(제출 대비) | GSC 스냅샷 (신규) |
| 5 | 돈이 되고 있나? | 애드센스 수익/RPM, 제휴 클릭 (Step 2 이후) | 수동 입력 또는 AdSense API |

> KPI 2번은 지금 이미 경보 구간입니다. 잔여 26편, `_approved` 큐 8건 —
> edu_weekly 발행 속도(로그 73건/약 8주)를 감안하면 몇 주 내 소진됩니다.

---

## 3. 아키텍처 제안 — 정적 대시보드

```
logs/runs.jsonl ─┐
logs/*.json      ├─→ tools/build_dashboard.py ─→ dashboard/data.json ─→ dashboard/index.html
data/metrics/*   ┘        (순수 함수, 네트워크 없음)                       (단일 HTML, 외부 CDN 없음)
data/edu_topics.json
```

**왜 정적인가**
- 이 프로젝트는 이미 "서버 없음(GitHub Actions + Blogger)"이 성립 조건입니다.
  Streamlit·Metabase·Grafana는 상시 서버·비용·인증을 새로 끌고 옵니다.
- 집계(Python)와 표현(HTML)을 `data.json` 이라는 **데이터 계약**으로 분리하면
  에이전트가 한쪽만 건드려도 다른 쪽이 깨지지 않습니다. 테스트도 집계 쪽만 하면 됩니다.
- 저장소가 private이면 GitHub Pages는 유료 플랜이 필요합니다. 그 경우
  ① Actions 아티팩트로 HTML 업로드 후 다운로드, ② 로컬에서 `dashboard/index.html` 열기 —
  둘 다 코드 변경 없이 동작합니다. (v1은 로컬 열기로 시작 권장)

**금지 사항**: 외부 차트 라이브러리 CDN. 인라인 SVG + 바닐라 JS로 충분하며,
CDN은 오프라인/사내망/CSP에서 그대로 빈 화면이 됩니다.

---

## 4. 개발 흐름 (Phase 0 → 4)

각 Phase는 **독립적으로 가치가 있고, 다음 Phase 없이도 버려지지 않게** 잘랐습니다.

### Phase 0 — 데이터 계약 고정 (대시보드 코드 0줄)
- [ ] `dashboard_schema.md` 작성: 모든 job이 남길 공통 실행 이벤트 스키마 정의
  ```json
  {"job":"kr_daily","run_date":"2026-08-27","started_at":"...","finished_at":"...",
   "status":"success|failed|skipped","stage":"collect|write|validate|publish",
   "error":"","url":"","char_count":0,"validation_issues":[],"run_id":"GH run id"}
  ```
- [ ] `shared/run_log.py` 신설: `record_run(...)` 한 함수. `logs/runs.jsonl` 에 **append**.
- [ ] 6개 `main.py` 의 모든 종료 경로(`sys.exit`, 예외 핸들러)에서 `record_run` 호출.
      기존 `save_log()` 와 `logs/*.json` 은 **그대로 둡니다**(하위 호환).
- ✅ 완료 기준: 일부러 실패시킨 dry-run 1회가 `runs.jsonl` 에 `status:"failed"` 로 남는다.

### Phase 1 — 지표 축적 시작 (UI 없음, 하지만 가장 급함)
- [ ] `tools/snapshot_gsc.py`: GSC 성과를 `data/metrics/gsc_YYYYMMDD.json` 으로 저장
- [ ] `.github/workflows/metrics_snapshot.yml`: 매일 1회 실행 + 커밋
- ✅ 완료 기준: 7일 연속 스냅샷 파일이 쌓인다. (이 시점부터 나중에 어떤 대시보드든 만들 수 있음)

### Phase 2 — 집계 스크립트 (테스트 가능한 순수 로직)
- [ ] `tools/build_dashboard.py`: 파일 읽기 → `dashboard/data.json` 출력. **네트워크 호출 금지.**
- [ ] `tests/test_build_dashboard.py`: 픽스처 로그 몇 건으로 KPI 계산 검증
      (특히 "발행 누락" 판정 — 주말·공휴일 제외 로직이 틀리기 쉬움)
- ✅ 완료 기준: `python tools/build_dashboard.py && python -m pytest tests/ -q` 통과

### Phase 3 — 화면 (단일 HTML)
- [ ] `dashboard/index.html`: `data.json` fetch → KPI 5개 렌더
- [ ] 상단은 차트가 아니라 **"오늘 조치가 필요한가"** 한 줄 상태 배너
- ✅ 완료 기준: 로컬에서 열어 5개 질문에 30초 안에 답할 수 있다

### Phase 4 — 자동화 & 경보
- [ ] nightly 워크플로에 대시보드 빌드 추가
- [ ] `kakao_notify` 확장: 발행 실패뿐 아니라 **"누락 감지"·"콘텐츠 재고 4주 미만"** 도 알림

---

## 5. 에이전트 지침 초안 (그대로 `CLAUDE.md` 에 복붙 가능)

> 현재 이 저장소에는 `CLAUDE.md` 가 없습니다. 아래를 루트에 두면 모든 세션이 읽습니다.
> 대시보드 전용 규칙은 `dashboard/CLAUDE.md` 로 분리하면 해당 디렉토리 작업 시에만 적용됩니다.

```markdown
# SeedUP INVEST — 대시보드 작업 지침

## 역할
너는 이 저장소의 운영 대시보드를 만든다. 대시보드는 "차트 모음"이 아니라
dashboard_plan.md 의 KPI 5개 질문에 답하는 도구다. 그 외 지표는 추가하지 않는다.

## 데이터에 관한 절대 규칙 (위반 시 작업 무효)
1. **없는 데이터를 만들어내지 않는다.** 값이 없으면 화면에 "—" 로 표시한다.
   0, "N/A 대신 추정치", 랜덤 목데이터, `or 0` 폴백을 절대 쓰지 않는다.
   (이 프로젝트는 금융 콘텐츠다. 가짜 숫자가 화면에 뜨는 순간 대시보드는 신뢰를 잃는다.)
2. 집계 스크립트(tools/build_dashboard.py)는 **네트워크를 호출하지 않는다.**
   외부 데이터는 별도 snapshot 스크립트가 파일로 떨군 것만 읽는다.
3. 로그 스키마가 job마다 다르다(kr_daily는 `date`, 나머지는 `kst_date` 등).
   분기 처리를 화면 코드에 흘리지 말고, 집계 단계에서 정규화한다.
4. 기존 logs/*.json 의 포맷·파일명을 바꾸지 않는다. 171건의 과거 이력이 여기 있다.

## 코드 규칙
- 표현(HTML)과 집계(Python)는 dashboard/data.json 계약으로만 통신한다.
- 외부 CDN·차트 라이브러리 금지. 인라인 SVG + 바닐라 JS.
- 주석은 기존 코드 스타일을 따른다 — 이 저장소는 "왜 이 코드가 있는지"를
  사고 이력과 함께 남기는 관행이 있다(shared/validator.py 참조). 그 밀도를 맞춘다.
- 파일 경로·함수명은 기존 관행을 따른다: 스크립트는 tools/, 공용 모듈은 shared/.

## 작업 흐름
- 한 번에 Phase 하나만 한다. Phase를 건너뛰지 않는다.
- 코드를 쓰기 전에 dashboard_plan.md 의 해당 Phase 완료 기준을 먼저 읽는다.
- 스키마를 바꿔야 한다고 판단되면, 코드를 고치기 전에 사용자에게 먼저 물어본다.

## 완료의 정의 (DoD) — 아래를 실행해 통과해야 "완료"라고 말한다
    python tools/build_dashboard.py
    python -m pytest tests/ -q
"통과했을 것이다"라고 쓰지 않는다. 실제 실행 출력을 근거로 보고한다.
실패하면 실패했다고 그대로 보고한다.

## 하지 말 것
- 발행 job(jobs/**/main.py)의 발행 로직 변경. 로그 기록 추가만 허용된다.
- 새 외부 서비스·유료 SaaS 도입 제안 없이 도입하기.
- 대시보드에 종목 추천·매매 신호성 지표 넣기 (유사투자자문업법 리스크, roadmap.md 참조).
```

---

## 6. 더 좋은 방안 — 제가 권하는 5가지

### ① 대시보드보다 "매일 아침 카톡 다이제스트"가 ROI가 10배다
1인 운영에서 대시보드는 만든 지 2주면 안 봅니다. 반면 이미 `shared/kakao_notify.py`
인프라가 있습니다. **매일 아침 카톡 1건**(어제 발행 6건 중 5건 성공 / 검증 이슈 0건 /
잔여 토픽 26편 / GSC 클릭 7일 대비 +12%)이 대시보드보다 실제로 운영을 바꿉니다.
→ **대시보드는 "다이제스트에서 이상이 잡혔을 때 파고드는 2차 도구"로 격하**시키고,
   Phase 4의 알림을 Phase 1로 끌어올리는 순서를 권합니다.

### ② 로그를 "이벤트 스트림"으로 (Phase 0의 핵심)
job별 개별 JSON 파일 대신 `logs/runs.jsonl` 한 줄 append 방식이면,
성공·실패·스킵이 한 파일에 시간순으로 쌓이고 집계가 `for line in f` 한 줄로 끝납니다.
GitHub Actions의 커밋 충돌(현재 `git pull --rebase` 로 처리 중)도 append-only가 훨씬 안전합니다.

### ③ "지침"보다 "실행 가능한 검증"을 신뢰하라
`shared/validator.py` 의 주석들이 좋은 증거입니다 — AI에게 "지침 문구를 본문에 남기지 마라"고
말하는 것보다 정규식 방어선을 두는 게 실제로 사고를 막았습니다(2026-07-13, 07-20, 07-28 사고 이력).
대시보드 에이전트 지침도 마찬가지입니다. **"목데이터 쓰지 마"라는 문장보다,
`data.json` 에 스키마 검증 테스트를 두는 게 강합니다.** 위 지침의 DoD에 명령어를 박아둔 이유입니다.

### ④ AI가 대시보드를 만들 때 가장 흔한 실패는 "그럴듯한 가짜 숫자"
차트를 먼저 만들라고 시키면 에이전트는 거의 항상 목데이터로 화면을 채우고,
그게 실데이터로 교체되지 않은 채 남습니다. 그래서 위 흐름은
**Phase 0~2(데이터) → Phase 3(화면)** 순서를 강제하고, 화면 작업을 마지막에 뒀습니다.
"예쁜 화면 먼저"의 유혹을 지침이 아니라 **순서**로 막는 구조입니다.

### ⑤ 지침은 계층화 + 스킬화
- 루트 `CLAUDE.md`: 저장소 공통(레드라인, 발행 파이프라인 불변식, 코드 관행)
- `dashboard/CLAUDE.md`: 대시보드 디렉토리 작업 시에만 로드
- `.claude/skills/`: "새 job 추가하기", "발행 사고 원인 추적하기" 같은
  반복 작업은 스킬로 캡슐화하면 매번 설명할 필요가 없어집니다.

---

## 7. 지금 당장 결정이 필요한 3가지

1. **알림 우선 vs 대시보드 우선** — 위 ①번 제안(다이제스트 먼저)을 받아들일지
2. **배포 위치** — 저장소가 public이면 GitHub Pages, private이면 로컬 열기로 시작
3. **Phase 0을 지금 진행할지** — 실패 로그 기록은 대시보드를 안 만들어도 그 자체로 가치가 있음
