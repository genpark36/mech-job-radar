# ALIO API 신청 체크리스트

이 문서는 실제 ALIO API 활용신청 뒤 개발 설정에 필요한 값을 빠르게 옮기기 위한 기록지다.

## 신청 대상

- 사이트: https://opendata.alio.go.kr/new/main.do
- 메뉴: `오픈 API신청`
- 사용자 상세 링크: https://opendata.alio.go.kr/new/odaApiUserInqDataMng/openApiRecrutDetail.do
- 우선 대상: 공공기관 채용정보 API
- 1차 필터: NCS분류 `기계` 코드 `R600015`, 상태 `진행`

## 명세에서 확인할 값

| 항목 | 확인값 |
|---|---|
| 호출 URL |  |
| 인증키 파라미터명 |  |
| 페이지 번호 파라미터명 |  |
| 페이지 크기 파라미터명 |  |
| 응답 형식 파라미터명 |  |
| JSON 요청 값 |  |
| 채용분야 필터 파라미터명 |  |
| 기계 분야 코드/값 |  |
| 진행 중 공고 필터 파라미터명 |  |
| 진행 상태 코드/값 |  |

## .env 작성 예시

```text
ALIO_API_URL=로그인 후 명세에서 확인한 실제 데이터 호출 URL
ALIO_API_KEY=발급받은 인증키
ALIO_API_KEY_PARAM=serviceKey
ALIO_DEFAULT_PARAMS={"pageNo":"1","numOfRows":"100","type":"json"}
MECH_JOB_RADAR_DB=data/job_radar.sqlite3
```

## 연결 진단

```powershell
$env:PYTHONPATH='src'
python -m job_radar check-config
python -m job_radar fetch-alio --dry-run --limit 5
```

## 실제 저장

```powershell
python -m job_radar fetch-alio --limit 5
python -m job_radar list-jobs --min-score 1
python -m job_radar write-dashboard
```

## 주의

- 인증키가 포함된 실제 응답 또는 URL을 문서에 그대로 붙이지 않는다.
- 응답 샘플을 저장할 때는 인증키와 개인 계정 정보가 없는지 확인한다.
- 사기업 사이트는 허용 여부 확인 전까지 이 프로젝트 범위에 넣지 않는다.
