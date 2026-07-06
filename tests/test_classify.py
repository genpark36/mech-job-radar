from job_radar.dashboard import FIT_MECH, FIT_NONE, FIT_REVIEW, classify_mechanical_fit


def fit(title, field="", category=""):
    row = {"title": title, "field": field}
    if category:
        row["raw_data"] = {"listCategory": category}
    return classify_mechanical_fit(row)["level"]


def test_strong_terms_classify_as_mech():
    assert fit("기계설계 경력직 채용") == FIT_MECH
    assert fit("설비보전 신입 모집") == FIT_MECH
    assert fit("플랜트 배관 시공 관리자") == FIT_MECH
    assert fit("MCT 가공 경력직") == FIT_MECH


def test_company_name_is_ignored():
    # 회사명에 "기계"가 있어도 직무가 사무면 무관이어야 한다
    row = {"title": "사무직 채용", "field": "", "company_name": "동양기계공업(주)"}
    assert classify_mechanical_fit(row)["level"] == FIT_NONE


def test_reject_terms_win_over_broad():
    assert fit("퍼포먼스 마케터 채용") == FIT_NONE
    assert fit("간호사 모집") == FIT_NONE
    assert fit("바리스타 정직원 모집") == FIT_NONE


def test_gongmuwon_not_confused_with_facility_gongmu():
    # "공무원"의 "공무"는 설비공무가 아니다
    assert fit("지방직 공무원 채용") != FIT_MECH
    # 진짜 설비공무는 기계직
    assert fit("공장 공무팀 사원 모집") == FIT_MECH


def test_broad_terms_are_review():
    assert fit("생산관리 신입/경력") == FIT_REVIEW
    assert fit("품질 담당자 채용") == FIT_REVIEW


def test_mechanical_category_promotes_only_safe_broad_terms():
    assert fit("생산직 정규직 채용", category="기계 직무 목록") == FIT_MECH
    # "엔지니어"는 기계 카테고리라도 승격하지 않는다 (AI 엔지니어 등 오탐)
    assert fit("AI 엔지니어 경력 채용", category="기계 직무 목록") == FIT_REVIEW


def test_category_alone_is_review_not_mech():
    assert fit("2026년 각 부문별 채용", category="기계 직무 목록") == FIT_REVIEW
    assert fit("2026년 각 부문별 채용") == FIT_NONE
