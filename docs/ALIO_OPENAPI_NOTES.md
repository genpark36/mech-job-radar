# ALIO OpenAPI 조사 메모

## 확인한 사실

- 공식 사이트: https://opendata.alio.go.kr/new/main.do
- 메인 메뉴에 `오픈API 찾기`, `오픈 API신청`, `채용정보`가 있다.
- 채용정보 조회 화면: https://opendata.alio.go.kr/new/odaApiMng/recrutInquiryList.do
- 채용정보 조회 화면에는 `채용분야` 필터가 있고, 값 중 `기계`가 존재한다.
- API 활용신청 상세는 로그인 후 접근된다.
- 사용자가 제공한 상세 링크 `https://opendata.alio.go.kr/new/odaApiUserInqDataMng/openApiRecrutDetail.do`는 비로그인 접근 시 로그인 화면으로 리다이렉트된다. 이 링크는 명세 확인용 화면이며, 실제 데이터 호출 URL은 로그인 후 명세 안의 호출 URL을 `.env`의 `ALIO_API_URL`에 넣어야 한다.
- `MOEF_NKOD_DB_05_CODE_DOC_v1.2.pdf`를 `docs/MOEF_NKOD_DB_05_CODE_DOC_v1.2.pdf`로 보존하고, 텍스트 추출본을 `docs/MOEF_NKOD_DB_05_CODE_DOC_v1.2.txt`로 저장했다.
- 공개 채용정보 조회 화면의 JavaScript에서 목록 endpoint를 확인했다.
  - URL: `https://opendata.alio.go.kr/new/odaApiMng/recrutInquiryAjaxList.do`
  - Method: `POST`
  - 기본 파라미터: `pageNo`, `numOfRows`, `ncsCdLst`, `ongoingYn`
  - 기계 진행 공고: `ncsCdLst=R600015`, `ongoingYn=Y`

## 코드 문서에서 확인한 핵심 채용 코드

| 구분 | 코드 | 값 |
|---|---|---|
| 고용형태 | R1010 | 정규직 |
| 고용형태 | R1050 | 청년인턴 |
| 고용형태 | R1060 | 청년인턴(체험형) |
| 고용형태 | R1070 | 청년인턴(채용형) |
| 채용구분 | R2010 | 신입 |
| 채용구분 | R2020 | 경력 |
| 채용구분 | R2030 | 신입+경력 |
| NCS분류 | R600015 | 기계 |
| NCS분류 | R600023 | 환경.에너지.안전 |
| 학력정보 | R7010 | 학력무관 |
| 학력정보 | R7050 | 대졸(4년) |

## 개발상 전제

ALIO API는 활용신청 후 인증키와 상세 호출 URL/파라미터를 확인해야 한다. 따라서 첫 코드에서는 API URL과 인증키를 환경변수로 주입한다.

```text
ALIO_API_URL=
ALIO_API_KEY=
ALIO_API_KEY_PARAM=serviceKey
ALIO_DEFAULT_PARAMS={"pageNo":"1","numOfRows":"100","type":"json"}
```

## 실제 API 명세 확인 후 업데이트할 항목

- 채용정보 목록 API endpoint
- 인증키 파라미터명
- 페이지 번호/페이지 크기 파라미터명
- JSON/XML 응답 여부
- 기관명, 제목, 시작일, 종료일, 채용분야, 고용형태, 채용구분, 근무지, 원문 URL 필드명
- 기계 분야 필터 파라미터 코드값

기계 분야 코드값은 코드 문서 기준 `R600015`로 확인했다. 다만 API 필터 파라미터명이 `ncsCd`, `ncsCdLst`, `ncsCdNmLst` 중 무엇인지는 실제 API 상세 명세에서 확인해야 한다.
