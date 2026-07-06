from job_radar.jasoseol_client import (
    format_api_date,
    normalize_jasoseol_record,
    parse_next_link,
)


SAMPLE_RECORD = {
    "id": 105005,
    "name": "동부건설(주)",
    "title": "경력사원(공사_기계/전기) 채용",
    "start_time": "2026-07-06T00:00:00.000+09:00",
    "end_time": "2026-07-19T23:50:00.000+09:00",
    "recruit_type": 0,
    "employment_page_url": "https://dongbucon.recruiter.co.kr/app/jobnotice/view?jobnoticeSn=259240",
    "employments": [
        {"id": 423673, "field": "건축사업본부-공사-기계-전국", "division": [2]},
        {"id": 423674, "field": "건축사업본부-공사-전기-전국", "division": [2]},
    ],
}


def test_normalize_record_maps_fields():
    job = normalize_jasoseol_record(SAMPLE_RECORD)
    assert job is not None
    assert job["company_name"] == "동부건설(주)"
    assert job["title"] == "경력사원(공사_기계/전기) 채용"
    assert job["source_platform"] == "jasoseol"
    assert job["source_record_id"] == "105005"
    assert job["url"] == "https://jasoseol.com/recruit/105005"
    assert job["external_url"].startswith("https://dongbucon.recruiter.co.kr/")
    assert job["posted_date"] == "2026-07-06"
    assert job["deadline"] == "2026-07-19"
    assert job["career_type"] == "경력"
    assert "기계" in job["field"]
    assert job["unique_key"]


def test_normalize_record_division_labels_joined():
    record = dict(SAMPLE_RECORD)
    record["employments"] = [
        {"id": 1, "field": "생산팀", "division": [1]},
        {"id": 2, "field": "설비팀", "division": [2, 3]},
    ]
    job = normalize_jasoseol_record(record)
    assert job["career_type"] == "신입/경력/인턴"


def test_normalize_record_requires_id_and_title():
    assert normalize_jasoseol_record({"id": "", "name": "x", "title": "y"}) is None
    assert normalize_jasoseol_record({"id": 5, "name": "x", "title": ""}) is None


def test_parse_next_link():
    header = (
        '<https://jasoseol.com/api/v1/employment_companies?page=10>; rel="last", '
        '<https://jasoseol.com/api/v1/employment_companies?page=2>; rel="next"'
    )
    assert (
        parse_next_link(header, base_url="https://jasoseol.com/api/v1/employment_companies?page=1")
        == "https://jasoseol.com/api/v1/employment_companies?page=2"
    )
    assert parse_next_link("", base_url="https://jasoseol.com/x") == ""


def test_format_api_date():
    assert format_api_date("2026-07-19T23:50:00.000+09:00") == "2026-07-19"
    assert format_api_date(None) == ""
    assert format_api_date("nonsense") == ""
