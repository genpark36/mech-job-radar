from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .platform_client import (
    assert_allowed_by_robots,
    clean_text,
    derive_career_type,
    derive_employment_type,
    fetch_text,
    first_location_tag,
    robots_url_for,
)


@dataclass(frozen=True)
class CompanyTarget:
    name: str
    group: str
    sector: str
    url: str
    enabled: bool = True
    parser: str = "generic"
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanyFetchResult:
    jobs: list[dict[str, Any]]
    duration_ms: int
    request_url: str
    robots_url: str


def load_company_targets(path: str | Path, *, include_disabled: bool = False) -> list[CompanyTarget]:
    target_path = Path(path)
    if not target_path.exists():
        return []
    with target_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    targets = []
    for item in data.get("targets", []):
        enabled = item.get("enabled", True) is not False
        if not enabled and not include_disabled:
            continue
        urls = item.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        for url_item in urls:
            if isinstance(url_item, str):
                url = url_item
                parser = str(item.get("parser") or "generic")
            else:
                url = str(url_item.get("url") or "")
                parser = str(url_item.get("parser") or item.get("parser") or "generic")
            if not item.get("name") or not url:
                continue
            targets.append(
                CompanyTarget(
                    name=str(item["name"]),
                    group=str(item.get("group") or ""),
                    sector=str(item.get("sector") or "사기업/민간"),
                    url=url,
                    enabled=enabled,
                    parser=parser,
                    keywords=tuple(str(keyword) for keyword in item.get("keywords", []) if keyword),
                )
            )
    return targets


def fetch_company_jobs(target: CompanyTarget, *, max_items: int = 80) -> CompanyFetchResult:
    assert_allowed_by_robots(target.url)
    start = time.perf_counter()
    if target.parser == "recruiter_mrs2":
        jobs = fetch_recruiter_mrs2_jobs(target, max_items=max_items)
    else:
        html_text = fetch_text(target.url)
        jobs = parse_generic_company_jobs(html_text, target=target, max_items=max_items)
    duration_ms = int((time.perf_counter() - start) * 1000)
    return CompanyFetchResult(
        jobs=jobs,
        duration_ms=duration_ms,
        request_url=target.url,
        robots_url=robots_url_for(target.url),
    )


def fetch_recruiter_mrs2_jobs(target: CompanyTarget, *, max_items: int) -> list[dict[str, Any]]:
    parsed = urllib.parse.urlparse(target.url)
    api_url = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, "/app/jobnotice/list.json", "", "", "")
    )
    data = urllib.parse.urlencode(
        {
            "recruitClassSn": "",
            "recruitClassName": "",
            "jobnoticeStateCode": "10",
            "pageSize": str(max_items),
            "searchByNameOnly": "true",
            "currentPage": "1",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=data,
        headers={
            "User-Agent": "PersonalJobMonitor/0.1 (+private low-frequency job alert use)",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    jobs = []
    for item in payload.get("list", [])[:max_items]:
        title = clean_text(str(item.get("jobnoticeName") or ""))
        notice_id = str(item.get("jobnoticeSn") or "")
        system_kind = str(item.get("systemKindCode") or "MRS2")
        if not title or not notice_id:
            continue
        detail_url = urllib.parse.urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                "/app/jobnotice/view",
                "",
                urllib.parse.urlencode(
                    {"systemKindCode": system_kind, "jobnoticeSn": notice_id}
                ),
                "",
            )
        )
        values = [title, target.name, target.group, str(item.get("recruitClassName") or ""), *target.keywords]
        location_values = [target.name, target.group, str(item.get("recruitClassName") or "")]
        jobs.append(
            {
                "company_name": target.name,
                "title": title,
                "url": detail_url,
                "external_url": detail_url,
                "source_platform": "company",
                "source_record_id": f"{parsed.netloc}:{notice_id}",
                "posted_date": format_recruiter_date(item.get("applyStartDate")),
                "deadline": format_recruiter_date(item.get("applyEndDate")),
                "field": "기업 직접 채용페이지",
                "employment_type": derive_employment_type(values),
                "career_type": derive_career_type(values),
                "location": first_location_tag(location_values),
                "raw_data": {
                    "sourcePlatform": "company",
                    "company": target.name,
                    "group": target.group,
                    "sector": target.sector,
                    "targetUrl": target.url,
                    "parser": target.parser,
                    "jobnoticeSn": notice_id,
                    "recruitClassName": item.get("recruitClassName") or "",
                    "receiptState": item.get("receiptState") or "",
                },
            }
        )
    for job in jobs:
        job["unique_key"] = company_record_id(
            str(job.get("source_platform", "")),
            str(job.get("source_record_id", "")),
        )
    return jobs


def parse_generic_company_jobs(
    html_text: str,
    *,
    target: CompanyTarget,
    max_items: int,
) -> list[dict[str, Any]]:
    parser = AnchorParser()
    parser.feed(html_text)
    jobs_by_key: dict[str, dict[str, Any]] = {}
    page_title = extract_title(html_text)
    for anchor in parser.anchors:
        href = html.unescape(anchor.get("href", "")).strip()
        text = clean_text(anchor.get("text", ""))
        label = text or clean_text(anchor.get("title", "")) or clean_text(anchor.get("aria", ""))
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full_url = urllib.parse.urljoin(target.url, href)
        title = normalize_company_title(label, full_url=full_url, target=target)
        if (
            not title
            or is_navigation_link(title, full_url)
            or not looks_like_recruit_item(title, full_url, target.keywords)
        ):
            continue
        record_id = company_record_id(target.name, full_url, title)
        if record_id in jobs_by_key:
            continue
        values = [title, full_url, page_title, target.name, target.group, *target.keywords]
        jobs_by_key[record_id] = {
            "company_name": target.name,
            "title": title,
            "url": full_url,
            "external_url": full_url,
            "source_platform": "company",
            "source_record_id": record_id,
            "posted_date": "",
            "deadline": "",
            "field": "기업 직접 채용페이지",
            "employment_type": derive_employment_type(values),
            "career_type": derive_career_type(values),
            "location": first_location_tag(values),
            "raw_data": {
                "sourcePlatform": "company",
                "company": target.name,
                "group": target.group,
                "sector": target.sector,
                "targetUrl": target.url,
                "href": full_url,
                "pageTitle": page_title,
                "parser": target.parser,
            },
        }
        if len(jobs_by_key) >= max_items:
            break
    jobs = list(jobs_by_key.values())
    for job in jobs:
        job["unique_key"] = company_record_id(
            str(job.get("source_platform", "")),
            str(job.get("source_record_id", "")),
            str(job.get("url", "")),
        )
    return jobs


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        href = attr_map.get("href", "")
        if not href:
            return
        self._current = {
            "href": href,
            "title": attr_map.get("title", ""),
            "aria": attr_map.get("aria-label", ""),
        }
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current is None:
            return
        self._current["text"] = clean_text(" ".join(self._text_parts))
        self.anchors.append(self._current)
        self._current = None
        self._text_parts = []


def extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.I | re.S)
    return clean_text(re.sub(r"<[^>]+>", " ", match.group(1))) if match else ""


def normalize_company_title(label: str, *, full_url: str, target: CompanyTarget) -> str:
    title = clean_text(label)
    if len(title) <= 1:
        path = urllib.parse.urlparse(full_url).path
        title = clean_text(path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " "))
    noise = {
        "company logo",
        "change cookie settings",
        "fraud warning",
        "join talent community",
        "jointalentcommunity",
        "채용",
        "채용정보",
        "채용공고",
        "모집공고",
        "공고 목록",
        "jobs",
        "apply",
        "recruit",
        "career",
    }
    if title.lower() in noise:
        return ""
    return title[:180]


def is_navigation_link(title: str, url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    lowered_url = url.lower()
    if any(
        token in lowered_url
        for token in (
            "/subsid/",
            "/faq",
            "/guide",
            "/myform",
            "/user/",
            "/life",
            "/people",
            "/story",
            "/private",
            "/privacy",
            "viewtype=resumeupdate",
            "instagram.com",
            "facebook.com",
            "youtube.com",
            "linkedin.com",
        )
    ):
        return True
    normalized_title = title.strip().lower()
    nav_titles = {
        "home",
        "main",
        "jobs",
        "job",
        "career",
        "careers",
        "apply",
        "채용",
        "채용정보",
        "채용공고",
        "모집공고",
        "관계사 소개",
        "지원 가이드",
        "나의 지원서",
        "지원서 수정",
        "아이디(이메일) 찾기",
        "비밀번호 찾기",
        "개인정보 처리방침",
        "개인정보처리방침",
        "스토리 전체 보러가기",
    }
    if title.endswith("보러가기") or "채용공고가 진행 중입니다" in title:
        return True
    if path in {"index", "jobs", "life", "people"}:
        return True
    if not path and len(normalized_title) <= 12:
        return True
    if normalized_title in nav_titles:
        return True
    detail_markers = ("detail", "view", "jobnotice", "recruit/", "apply/")
    if any(marker in url.lower() for marker in detail_markers):
        return False
    return len(title) <= 8


def looks_like_recruit_item(title: str, url: str, target_keywords: tuple[str, ...]) -> bool:
    title_text = title.lower()
    url_text = url.lower()
    text = f"{title_text} {url_text}"
    title_recruit_tokens = (
        "채용",
        "모집",
        "공고",
        "지원",
        "신입",
        "경력",
        "인턴",
        "recruit",
        "job",
        "position",
        "opening",
        "vacancy",
    )
    url_detail_tokens = (
        "/jobs/",
        "/job/",
        "/apply/",
        "/recruit/",
        "jobnotice",
        "jobid",
        "job_id",
        "jobseq",
        "requisition",
        "reqid",
    )
    mechanical_tokens = (
        "기계",
        "설비",
        "정비",
        "생산",
        "제조",
        "공정",
        "품질",
        "안전",
        "자동차",
        "반도체",
        "방산",
        "플랜트",
        "장비",
        "r&d",
        "engineer",
        "manufacturing",
        "production",
        "quality",
        "maintenance",
    )
    if any(keyword.lower() in text for keyword in target_keywords):
        return True
    if any(token in title_text for token in title_recruit_tokens):
        return True
    if any(token in text for token in mechanical_tokens):
        return True
    return any(token in url_text for token in url_detail_tokens)


def company_record_id(*parts: str) -> str:
    base = "|".join(parts)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def format_recruiter_date(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    timestamp = value.get("time")
    if timestamp is None:
        return ""
    try:
        kst = timezone(timedelta(hours=9))
        dt = datetime.fromtimestamp(int(timestamp) / 1000, tz=timezone.utc).astimezone(kst)
    except (TypeError, ValueError, OSError):
        return ""
    return dt.strftime("%Y-%m-%d")
