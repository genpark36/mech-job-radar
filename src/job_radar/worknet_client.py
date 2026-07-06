from __future__ import annotations

import hashlib
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorknetFetchResult:
    jobs: list[dict[str, Any]]
    duration_ms: int
    request_url: str
    total: int


def fetch_worknet_jobs(
    *,
    api_url: str,
    api_key: str,
    keywords: list[str],
    occupations: list[str] | None = None,
    display: int = 100,
    max_pages: int = 20,
) -> WorknetFetchResult:
    if not api_url:
        raise ValueError("WORKNET_API_URL is not configured")
    if not api_key:
        raise ValueError("WORKNET_API_KEY is not configured")

    start = time.perf_counter()
    jobs_by_id: dict[str, dict[str, Any]] = {}
    total = 0
    last_url = ""
    for query in build_queries(keywords, occupations or []):
        for page in range(1, max_pages + 1):
            params = {
                "authKey": api_key,
                "callTp": "L",
                "returnType": "XML",
                "startPage": str(page),
                "display": str(display),
            }
            params.update(query["params"])
            url = build_url(api_url, params)
            last_url = redact_url(url, api_key)
            root = fetch_xml(url)
            error = text_of(root, "error")
            if error:
                raise ValueError(error)
            message_code = text_of(root, "messageCd")
            if message_code and message_code != "000":
                message = text_of(root, "message") or f"Worknet error code {message_code}"
                raise ValueError(message)
            total = max(total, int_or_zero(text_of(root, "total")))
            records = root.findall(".//wanted")
            if not records:
                break
            for record in records:
                job = normalize_worknet_record(record, query["label"])
                if job["source_record_id"]:
                    jobs_by_id[job["source_record_id"]] = job
            if len(records) < display:
                break

    duration_ms = int((time.perf_counter() - start) * 1000)
    return WorknetFetchResult(
        jobs=list(jobs_by_id.values()),
        duration_ms=duration_ms,
        request_url=last_url,
        total=total,
    )


def build_queries(keywords: list[str], occupations: list[str]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for keyword in keywords:
        if keyword:
            queries.append({"label": f"키워드:{keyword}", "params": {"keyword": keyword}})
    for occupation in occupations:
        if occupation:
            queries.append({"label": f"직종:{occupation}", "params": {"occupation": occupation}})
    return queries


def fetch_xml(url: str) -> ET.Element:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "PersonalJobMonitor/0.1 (+private Worknet API use)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read()
    return ET.fromstring(body.decode("utf-8", errors="replace"))


def normalize_worknet_record(record: ET.Element, keyword: str) -> dict[str, Any]:
    source_record_id = first_text(
        record,
        "wantedAuthNo",
        "wantedAuthNoScr",
        "wantedNo",
        "jobId",
    )
    title = first_text(record, "title", "wantedTitle")
    company_name = first_text(record, "company", "corpNm", "busino")
    url = first_text(record, "wantedInfoUrl", "detailUrl", "infoUrl")
    career_type = first_text(record, "career", "careerMin", "careerCdNm")
    employment_type = first_text(record, "holidayTpNm", "empTpNm", "employmentType")
    location = first_text(record, "region", "basicAddr", "workRegion")
    deadline = first_text(record, "closeDt", "wantedCloseDt")
    posted_date = first_text(record, "regDt", "wantedRegDt")
    field = first_text(record, "jobsCd", "jobsNm", "jobCont") or f"워크넷 검색어: {keyword}"
    job = {
        "company_name": company_name or "워크넷",
        "title": title or "제목 미확인 공고",
        "url": url,
        "external_url": url,
        "source_platform": "worknet",
        "source_record_id": source_record_id,
        "posted_date": posted_date,
        "deadline": deadline,
        "field": field,
        "employment_type": employment_type,
        "career_type": career_type,
        "location": location,
        "raw_data": {
            "sourcePlatform": "worknet",
            "keyword": keyword,
            "wantedAuthNo": source_record_id,
        },
    }
    job["unique_key"] = unique_key(job)
    return job


def first_text(record: ET.Element, *names: str) -> str:
    for name in names:
        value = text_of(record, name)
        if value:
            return value
    return ""


def text_of(element: ET.Element, name: str) -> str:
    found = element.find(name)
    if found is not None and found.text:
        return " ".join(found.text.split())
    found = element.find(f".//{name}")
    if found is not None and found.text:
        return " ".join(found.text.split())
    return ""


def int_or_zero(value: str) -> int:
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else 0


def build_url(api_url: str, params: dict[str, str]) -> str:
    delimiter = "&" if "?" in api_url else "?"
    return f"{api_url}{delimiter}{urllib.parse.urlencode(params)}"


def redact_url(url: str, key: str) -> str:
    return url.replace(key, "***") if key else url


def unique_key(job: dict[str, Any]) -> str:
    base = "|".join(
        [
            str(job.get("source_platform", "")),
            str(job.get("source_record_id", "")),
            str(job.get("company_name", "")),
            str(job.get("title", "")),
            str(job.get("url", "")),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()
