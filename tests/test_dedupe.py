from job_radar.dashboard import merge_duplicate_jobs
from job_radar.db import dedupe_group_key, normalize_company


def test_normalize_company_strips_corporate_suffixes():
    assert normalize_company("(주)한화에어로스페이스") == normalize_company("한화에어로스페이스")
    assert normalize_company("㈜두산 에너빌리티") == normalize_company("두산에너빌리티")
    assert normalize_company("주식회사 기가") == normalize_company("기가")


def test_dedupe_group_key_matches_across_platforms():
    key_a = dedupe_group_key("(주)쿠팡로지스틱스서비스", "[연최대5020만] 물류 알바관리자 채용(헬퍼리더)")
    key_b = dedupe_group_key("쿠팡로지스틱스서비스", "[연최대5020만] 물류 알바관리자 채용 (헬퍼리더)")
    assert key_a and key_a == key_b


def test_dedupe_group_key_empty_when_missing_parts():
    assert dedupe_group_key("", "제목") == ""
    assert dedupe_group_key("회사", "") == ""


def test_merge_duplicate_jobs_combines_sources():
    rows = [
        {
            "company_name": "쿠팡로지스틱스서비스(유)",
            "title": "물류 알바관리자 채용",
            "source_platform": "jobkorea",
            "score": 5,
            "deadline": "",
        },
        {
            "company_name": "쿠팡로지스틱스서비스(유)",
            "title": "물류 알바관리자 채용",
            "source_platform": "saramin",
            "score": 8,
            "deadline": "~07.31(금)",
            "matched_keywords": "물류(+5)",
        },
        {
            "company_name": "다른회사",
            "title": "기계설계 채용",
            "source_platform": "jobkorea",
            "score": 10,
        },
    ]
    merged = merge_duplicate_jobs(rows)
    assert len(merged) == 2
    combined = merged[0]
    assert combined["_source_platforms"] == ["jobkorea", "saramin"]
    assert combined["score"] == 8
    assert combined["deadline"] == "~07.31(금)"


def test_merge_duplicate_jobs_keeps_rows_without_key():
    rows = [
        {"company_name": "", "title": "제목만 있는 행", "source_platform": "jobkorea", "score": 0},
        {"company_name": "", "title": "제목만 있는 행", "source_platform": "saramin", "score": 0},
    ]
    assert len(merge_duplicate_jobs(rows)) == 2
