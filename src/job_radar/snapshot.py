from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import ensure_source, insert_jobs, log_crawl, mark_source_success


KST = ZoneInfo("Asia/Seoul")

DEFAULT_SNAPSHOT_PATH = Path("data/alio_snapshot.json")

SNAPSHOT_SOURCE_URL = "local://alio-snapshot"

JOB_COLUMNS = (
    "company_name",
    "title",
    "url",
    "source_platform",
    "source_record_id",
    "alio_detail_url",
    "external_url",
    "unique_key",
    "posted_date",
    "deadline",
    "field",
    "employment_type",
    "career_type",
    "location",
    "score",
    "detected_at",
)


def export_alio_snapshot(conn: sqlite3.Connection, path: str | Path = DEFAULT_SNAPSHOT_PATH) -> int:
    rows = conn.execute(
        f"""
        SELECT {", ".join(JOB_COLUMNS)}, matched_keywords, raw_data
        FROM detected_jobs
        WHERE source_platform = 'alio'
        ORDER BY source_record_id
        """
    ).fetchall()
    jobs = []
    for row in rows:
        job = {column: row[column] for column in JOB_COLUMNS}
        job["matched_keywords"] = parse_json_list(row["matched_keywords"])
        job["raw_data"] = parse_json_dict(row["raw_data"])
        jobs.append(job)
    payload = {
        "exported_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "count": len(jobs),
        "jobs": jobs,
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(jobs)


def import_alio_snapshot(conn: sqlite3.Connection, path: str | Path = DEFAULT_SNAPSHOT_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    jobs = payload.get("jobs", [])
    exported_at = str(payload.get("exported_at", ""))
    source_id = ensure_source(conn, url=SNAPSHOT_SOURCE_URL, platform="alio", source_type="snapshot")
    inserted = insert_jobs(conn, jobs, source_id)
    log_crawl(
        conn,
        source_id=source_id,
        status="alio_snapshot",
        new_jobs_count=inserted,
        error_message=f"스냅샷 기준 {exported_at}" if exported_at else "",
    )
    mark_source_success(conn, source_id)
    return {"total": len(jobs), "inserted": inserted, "exported_at": exported_at}


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def parse_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
