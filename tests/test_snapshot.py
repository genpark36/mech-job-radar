import sqlite3

from job_radar.db import ensure_source, init_db, insert_jobs
from job_radar.snapshot import export_alio_snapshot, import_alio_snapshot


SAMPLE_JOB = {
    "company_name": "한국수자원공사",
    "title": "2026년 기계직 신입 채용",
    "url": "https://opendata.alio.go.kr/new/odaApiMng/recrutInquiryDetail.do?sn=12345",
    "source_platform": "alio",
    "source_record_id": "12345",
    "alio_detail_url": "https://opendata.alio.go.kr/new/odaApiMng/recrutInquiryDetail.do?sn=12345",
    "external_url": "https://kwater.recruiter.co.kr/",
    "unique_key": "abc123",
    "posted_date": "2026-07-01",
    "deadline": "2026-07-20",
    "field": "기계",
    "employment_type": "정규직",
    "career_type": "신입",
    "location": "대전",
    "score": 13,
    "matched_keywords": ["기계(+8)", "신입(+5)"],
    "raw_data": {"recrutPblntSn": "12345"},
}


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_snapshot_roundtrip(tmp_path):
    source = make_db()
    source_id = ensure_source(source, url="test://alio", platform="alio", source_type="api")
    insert_jobs(source, [dict(SAMPLE_JOB)], source_id)
    path = tmp_path / "alio_snapshot.json"
    count = export_alio_snapshot(source, path)
    assert count == 1

    target = make_db()
    result = import_alio_snapshot(target, path)
    assert result["total"] == 1
    assert result["inserted"] == 1
    row = target.execute(
        "SELECT company_name, title, deadline, score, source_record_id FROM detected_jobs"
    ).fetchone()
    assert row["company_name"] == "한국수자원공사"
    assert row["title"] == "2026년 기계직 신입 채용"
    assert row["deadline"] == "2026-07-20"
    assert row["score"] == 13
    assert row["source_record_id"] == "12345"

    # 두 번 불러와도 중복 생성되지 않는다
    result2 = import_alio_snapshot(target, path)
    assert result2["inserted"] == 0
    assert target.execute("SELECT COUNT(*) FROM detected_jobs").fetchone()[0] == 1


def test_export_only_alio_rows(tmp_path):
    conn = make_db()
    source_id = ensure_source(conn, url="test://alio", platform="alio", source_type="api")
    platform_job = dict(SAMPLE_JOB)
    platform_job.update(
        source_platform="jobkorea", source_record_id="99", unique_key="zzz", title="플랫폼 공고"
    )
    insert_jobs(conn, [dict(SAMPLE_JOB), platform_job], source_id)
    path = tmp_path / "snap.json"
    assert export_alio_snapshot(conn, path) == 1
