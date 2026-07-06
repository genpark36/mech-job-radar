# 채용 공고

개인용 기계직/기계공학 직무 채용 모니터입니다.

1차 목표는 ALIO로 공공기관 채용을 안정적으로 잡고, 잡코리아/사람인/자소설닷컴 공개 목록과 관심기업 직접 채용페이지를 보조 소스로 겹쳐 누락 가능성을 줄이는 것입니다.

## 현재 범위

- ALIO 공공기관 채용정보 API 설정 기반 수집
- SQLite 저장
- 기계직/생산기술 계열 키워드 점수 계산
- 기계직/참고/무관 3단계 분류 (제목·모집분야 + 수집 목록 카테고리 기반)
- 회사별 그룹 접기/펼치기 대시보드, 기계직 기본 탭, NEW·D-day 뱃지
- 신규 공고 중복 방지용 `unique_key` 저장
- ALIO 상세 링크와 외부 원문 링크 분리 저장
- robots.txt 허용 경로만 확인하는 채용 플랫폼 공개 목록 수집
- 잡코리아/사람인 공개 목록 다중 페이지 수집
- 자소설닷컴 공개 채용 JSON API 수집 (`fetch-platform --platform jasoseol`)
- 관심기업 직접 채용페이지 수집 (`config/company_targets.json`)
- 같은 회사+제목 공고의 출처 병합 표시 (잡코리아·사람인 중복 제거)
- 오염 데이터 정리 명령 (`cleanup-jobs`)
- 경력, 고용형태, 지역, 공기업/사기업/공무원 구분 표시
- 검색어 AND/OR, 경력 AND/OR, 오름차순/내림차순 정렬
- KST 06:00/12:00/18:00/24:00 자동 갱신 기준
- Telegram 알림 설정 준비

## 빠른 시작

```powershell
Copy-Item .env.example .env
notepad .env
$env:PYTHONPATH='src'
python -m job_radar init-db
python -m job_radar check-config
python -m job_radar import-sample docs/samples/alio_recruitment_sample.json
python -m job_radar fetch-alio-public --dry-run --limit 5
python -m job_radar fetch-alio-public --limit 5
python -m job_radar fetch-platform --platform jobkorea --dry-run --limit 10
python -m job_radar fetch-platform --platform saramin --dry-run --limit 10
python -m job_radar fetch-platform --platform jasoseol --dry-run --limit 10
python -m job_radar fetch-company --dry-run --limit 10
python -m job_radar fetch-all
python -m job_radar cleanup-jobs
python -m job_radar audit-sources
python -m job_radar list-jobs --min-score 1
python -m job_radar write-dashboard
python -m job_radar serve
python -m job_radar fetch-alio --dry-run
```

ALIO API 활용신청 후 `.env`에 `ALIO_API_URL`, `ALIO_API_KEY`를 채워야 실제 API 호출이 가능합니다. 값을 넣은 뒤 `python -m job_radar check-config`로 인증키가 마스킹된 요청 URL을 확인하세요.

현재 실제 수집은 공개 조회 endpoint인 `fetch-alio-public`으로 먼저 가능합니다. 기본값은 진행 중인 NCS 건설, 기계, 재료, 화학, 전기전자, 환경·에너지·안전, 연구 공고를 나눠서 조회합니다.

채용 플랫폼은 `fetch-platform`으로 공개 목록 페이지만 저빈도 수집합니다. 현재는 잡코리아/사람인 공개 채용목록 파서와 자소설닷컴 공개 JSON API를 지원하며, 실행 전 대상 URL이 `robots.txt`에서 허용되는지 검사합니다. 기본 저장 기준은 사실상 전체 저장이라 누락을 줄이고, 점수는 우선순위 정렬용으로 사용합니다.

파서 문제 등으로 잘못 저장된 행(제목이 "스크랩", 회사명이 플랫폼 폴백값)은 `python -m job_radar cleanup-jobs`로 확인하고 `--apply`로 정리합니다. 같은 공고가 여러 플랫폼에 올라온 경우 DB에는 각각 저장하되 대시보드에서 출처를 병합해 한 줄로 보여줍니다.

테스트는 `python -m pytest`로 실행합니다 (파서/중복 병합/자소설 매핑 회귀 테스트).

관심기업 직접 소스는 `config/company_targets.json`에 추가합니다. `enabled: true`인 기업만 자동 수집하며, JavaScript 앱이거나 목록 구조가 특이해서 검증되지 않은 기업은 `enabled: false`로 목록에만 남깁니다. 특정 기업이 잘 안 잡히면 그 기업만 전용 파서를 추가하는 방식으로 확장합니다.

대량 기업 목록은 엑셀을 먼저 레지스트리와 링크 대기열로 가져온 뒤, 채용 URL을 확인한 회사부터 하나씩 연결합니다.

```powershell
python -m job_radar import-company-xlsx data/raw/company_list.xlsx --grades A,B
python -m job_radar import-company-watchlist data/raw/company_list.xlsx --grades A,B,C,D
python -m job_radar tag-existing-watchlist
python -m job_radar audit-sources
python -m job_radar company-link-queue --grade A --limit 20
python -m job_radar discover-company-links --provider generated --grade A --limit 20
python -m job_radar company-link-candidates --limit 20 --per-company 5
python -m job_radar set-company-link --name ABB코리아 --url https://careers.abb/global/en/search-results
python -m job_radar fetch-company --name ABB코리아 --dry-run --limit 10
```

`import-company-xlsx`는 `config/company_registry.json`과 `config/company_link_queue.json`을 만듭니다. 엑셀에는 채용 URL이 없으므로 `company_link_queue.json`의 `suggested_searches`로 공식 채용페이지를 확인하고, `set-company-link`로 붙입니다. 기본은 `enabled: false`라서 자동 수집에는 들어가지 않습니다. 드라이런 결과가 공고 목록으로 정상 파싱될 때만 `--enable`을 붙여 활성화하세요.

`discover-company-links`는 대기열의 회사명을 이용해 `config/company_link_candidates.json`에 주소 후보를 만듭니다. 기본 `generated` 방식은 사람인/잡코리아 검색 주소와 수동 확인용 검색 주소를 생성합니다. `.env`에 `BRAVE_SEARCH_API_KEY`를 넣고 `--provider brave` 또는 `--provider auto`를 쓰면 웹 검색 결과의 공식 채용페이지 후보까지 함께 저장합니다. 검색 결과는 오탐이 있을 수 있으므로 바로 자동 활성화하지 말고 `company-link-candidates`로 본 뒤 `set-company-link`와 `fetch-company --dry-run`으로 검증하세요.

전국 기업 목록은 두 갈래로 씁니다.

- `company_registry.json`: A/B 기업의 공식 채용페이지 직접 연결 작업용입니다.
- `company_watchlist.json`: A-D 전체 기업을 플랫폼 수집 결과와 매칭하는 감지용입니다.

`import-company-watchlist`는 원본 엑셀의 A-D 전체 기업을 `config/company_watchlist.json`에 넣습니다. 이후 플랫폼/기업/ALIO 수집 결과의 회사명이 watchlist와 맞으면 공고에 `관심기업 A/B/C/D` 태그가 붙고, 대시보드에서 관심기업 필터로 확인할 수 있습니다. 기존 DB에 이미 저장된 공고는 `tag-existing-watchlist`로 한 번 태깅하세요.

Worknet은 개인회원 키로 채용정보 API가 막히는 경우가 있어 기본 비활성화되어 있습니다. 기관/사업자 권한으로 정상 호출 가능한 키를 확보했을 때만 `.env`나 GitHub Secrets에 `WORKNET_ENABLED=1`을 넣어 켜세요.

상세 개발 메모는 [docs/개발_매뉴얼.md](docs/개발_매뉴얼.md)를 보세요.

정적 대시보드는 `python -m job_radar write-dashboard` 실행 후 `data/dashboard.html`에서 확인할 수 있습니다. 모든 저장 공고를 한 번에 넣고, 브라우저에서 적합도/출처/경력/점수/검색어로 필터링합니다.

소스 상태는 `python -m job_radar audit-sources`로 확인합니다. 대시보드에도 `수집 소스 상태` 표가 표시되어, 어느 출처가 정상/차단/실패인지와 최근 신규 건수를 바로 볼 수 있습니다.

누락을 줄이기 위해 기본 정책은 자동 제외가 아니라 전체 저장입니다. 대시보드의 `기계직` 탭이 기본 화면(바로 볼 공고)이고, `참고`는 기계직일 수도 있는 넓은 후보, `무관`은 전체 탭에서만 보입니다. 분류는 회사명을 제외한 제목·모집분야 텍스트와 수집 목록 카테고리(잡코리아 기계 직무 페이지, 사람인 생산/연구 직종 페이지)를 사용합니다.

계속 작동하는 로컬 서버는 `python -m job_radar serve`로 실행합니다. 서버는 시작 시 1회 수집하고, 이후 KST 기준 00/06/12/18시에 자동 수집합니다. 주소는 기본 `http://127.0.0.1:8787`입니다.

## 무료 배포 권장안

개인용 무료 배포는 GitHub Actions + GitHub Pages 구성을 권장합니다.

- `.github/workflows/crawl-and-publish.yml`이 매일 KST 06:00, 12:00, 18:00, 24:00에 실행됩니다.
- Actions에서 Python 크롤러를 실행한 뒤 `site/index.html`을 만들고 GitHub Pages에 배포합니다.
- 수동 갱신은 GitHub Actions 화면의 `workflow_dispatch`로 실행할 수 있습니다.
- API 키는 저장소에 커밋하지 말고 GitHub repository secrets에 넣습니다.

필요한 Secrets:

- `ALIO_API_URL`
- `ALIO_API_KEY`
- `ALIO_API_KEY_PARAM` 선택, 기본값을 쓰면 생략 가능
- `ALIO_PUBLIC_URL` 선택, 기본값을 쓰면 생략 가능
- `ALIO_PUBLIC_DEFAULT_PARAMS` 선택
- `WORKNET_API_URL` 선택, 기본값을 쓰면 생략 가능
- `WORKNET_API_KEY`
- `WORKNET_ENABLED` 선택, 정상 사용 가능한 키가 있을 때만 `1`
- `WORKNET_KEYWORDS` 선택
- `WORKNET_OCCUPATIONS` 선택, 정확한 고용24 직종코드를 확보했을 때 쉼표로 입력
- `COMPANY_TARGETS_PATH` 선택, 기본값은 `config/company_targets.json`

이 폴더를 별도 GitHub 저장소로 올릴 경우 워크플로가 그대로 동작합니다. 현재 큰 capstoneapp 저장소 안에 하위 폴더로 둘 경우에는 `.github/workflows/crawl-and-publish.yml`을 저장소 루트의 `.github/workflows/`로 옮기고, 각 명령에 `working-directory: mech-job-radar`를 붙여야 합니다.
