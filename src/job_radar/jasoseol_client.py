from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .platform_client import (
    USER_AGENT,
    assert_allowed_by_robots,
    clean_text,
    clean_title,
    derive_career_type,
    robots_url_for,
    unique_key,
)


JASOSEOL_API_URL = "https://jasoseol.com/api/v1/employment_companies"
JASOSEOL_RECRUIT_URL = "https://jasoseol.com/recruit"

# employments[].division 코드 → 채용 구분
DIVISION_LABELS = {
    1: "신입",
    2: "경력",
    3: "인턴",
}


@dataclass(frozen=True)
class JasoseolFetchResult:
    jobs: list[dict[str, Any]]
    duration_ms: int
    request_url: str
    robots_url: str


def fetch_jasoseol_jobs(*, max_items: int = 300, max_pages: int = 10) -> JasoseolFetchResult:
    assert_allowed_by_robots(JASOSEOL_API_URL)
    start = time.perf_counter()
    jobs: list[dict[str, Any]] = []
    url = f"{JASOSEOL_API_URL}?page=1"
    pages = 0
    while url and pages < max_pages and len(jobs) < max_items:
        records, next_url = fetch_page(url)
        pages += 1
        for record in records:
            job = normalize_jasoseol_record(record)
            if job:
                jobs.append(job)
            if len(jobs) >= max_items:
                break
        url = next_url
    duration_ms = int((time.perf_counter() - start) * 1000)
    return JasoseolFetchResult(
        jobs=jobs,
        duration_ms=duration_ms,
        request_url=f"{JASOSEOL_API_URL}?page=1",
        robots_url=robots_url_for(JASOSEOL_API_URL),
    )


def fetch_page(url: str) -> tuple[list[dict[str, Any]], str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read()
        link_header = response.headers.get("Link", "")
    records = json.loads(body.decode("utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"Unexpected jasoseol payload: {type(records).__name__}")
    return records, parse_next_link(link_header, base_url=url)


def parse_next_link(link_header: str, *, base_url: str) -> str:
    for part in link_header.split(","):
        match = re.search(r'<([^>]+)>\s*;\s*rel="next"', part)
        if match:
            return urllib.parse.urljoin(base_url, match.group(1))
    return ""


def normalize_jasoseol_record(record: dict[str, Any]) -> dict[str, Any] | None:
    record_id = str(record.get("id") or "").strip()
    company = clean_text(str(record.get("name") or ""))
    title, _ = clean_title(str(record.get("title") or ""))
    if not record_id or not title:
        return None
    employments = record.get("employments") or []
    fields = []
    divisions: set[int] = set()
    for employment in employments:
        if not isinstance(employment, dict):
            continue
        field = clean_text(str(employment.get("field") or ""))
        if field and field not in fields:
            fields.append(field)
        for code in employment.get("division") or []:
            if isinstance(code, int):
                divisions.add(code)
    career_parts = [DIVISION_LABELS[code] for code in sorted(divisions) if code in DIVISION_LABELS]
    career_type = "/".join(career_parts) or derive_career_type([title])
    detail_url = f"{JASOSEOL_RECRUIT_URL}/{record_id}"
    external_url = clean_text(str(record.get("employment_page_url") or ""))
    job = {
        "company_name": company,
        "title": title,
        "url": detail_url,
        "external_url": external_url,
        "source_platform": "jasoseol",
        "source_record_id": record_id,
        "posted_date": format_api_date(record.get("start_time")),
        "deadline": format_api_date(record.get("end_time")),
        "field": " / ".join(fields[:5]),
        "employment_type": "",
        "career_type": career_type,
        "location": "",
        "raw_data": {
            "sourcePlatform": "jasoseol",
            "jasoseolId": record_id,
            "employmentPageUrl": external_url,
            "recruitType": record.get("recruit_type"),
            "divisions": sorted(divisions),
            "fields": fields,
        },
    }
    job["unique_key"] = unique_key(job)
    return job


def format_api_date(value: Any) -> str:
    text = str(value or "")
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
