from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


USER_AGENT = "PersonalJobMonitor/0.1 (+private low-frequency job alert use)"


class RobotsBlockedError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlatformFetchResult:
    jobs: list[dict[str, Any]]
    duration_ms: int
    request_url: str
    robots_url: str


def fetch_platform_jobs(
    *,
    platform: str,
    url: str,
    max_items: int = 80,
) -> PlatformFetchResult:
    if platform not in ("jobkorea", "saramin"):
        raise ValueError(f"Unsupported platform: {platform}")
    assert_allowed_by_robots(url)

    start = time.perf_counter()
    html_text = fetch_text(url)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if platform == "jobkorea":
        jobs = parse_jobkorea_jobs(html_text, base_url=url, max_items=max_items)
    else:
        jobs = parse_saramin_jobs(html_text, base_url=url, max_items=max_items)
    return PlatformFetchResult(
        jobs=jobs,
        duration_ms=duration_ms,
        request_url=url,
        robots_url=robots_url_for(url),
    )


def assert_allowed_by_robots(url: str) -> None:
    robots_url = robots_url_for(url)
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        robots_text = fetch_text(robots_url)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RobotsBlockedError(f"robots.txt request rejected ({exc.code}): {robots_url}")
        if 400 <= exc.code < 500:
            return
        raise
    parser.parse(robots_text.splitlines())
    if not parser.can_fetch(USER_AGENT, url):
        raise RobotsBlockedError(f"robots.txt blocks this URL: {url}")


def robots_url_for(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read()
        content_type = response.headers.get("Content-Type", "")
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, flags=re.I)
    if match:
        charset = match.group(1)
    return body.decode(charset, errors="replace")


def parse_jobkorea_jobs(html_text: str, *, base_url: str, max_items: int) -> list[dict[str, Any]]:
    jobs_by_id: dict[str, dict[str, Any]] = {}
    for block in extract_list_blocks(html_text, "devloopArea"):
        href = first_match(block, r'href=["\']([^"\']*/Recruit/GI_Read/[^"\']*)["\']')
        job_id = extract_jobkorea_id(href)
        if not job_id:
            continue
        full_url = urllib.parse.urljoin(base_url, html.unescape(href))
        full_url = normalize_jobkorea_url(full_url)
        onclick_company, onclick_title = parse_jobkorea_onclick(
            first_match(block, r'onclick=["\']([^"\']+)["\']')
        )
        company = strip_tags(first_match(block, r'<span class="company-name">\s*<a[^>]*>(.*?)</a>'))
        company = company or strip_tags(first_match(block, r'<span class="name">\s*<a[^>]*>(.*?)</a>'))
        company = company or clean_text(first_match(block, r'<img[^>]+alt=["\']([^"\']+?)\s*썸네일["\']'))
        company = company or onclick_company
        title = strip_tags(first_match(block, r'<p class="title">\s*<a[^>]*>(.*?)</a>'))
        title = title or strip_tags(first_match(block, r'<span class="text">(.*?)</span>'))
        if not title:
            description = first_match(block, r'<div class="description">\s*<a[^>]*>(.*?)</a>')
            description = re.sub(r'<span class="dday".*$', "", description, flags=re.S)
            title = strip_tags(description)
        title = title or onclick_title
        tags = [strip_tags(item) for item in re.findall(r'<li class="tag">(.*?)</li>', block, flags=re.S)]
        deadline = strip_tags(first_match(block, r'<div class="deadline">\s*(.*?)\s*</div>'))
        deadline = deadline or strip_tags(first_match(block, r'<span class="deadLine">(.*?)</span>'))
        title, title_deadline = clean_title(title)
        deadline = deadline or title_deadline
        career_type = derive_career_type(tags + [title])
        employment_type = derive_employment_type(tags + [title])
        location = first_location_tag(tags)
        if not title:
            continue

        existing = jobs_by_id.get(job_id)
        if existing and len(str(existing.get("title", ""))) >= len(title):
            continue
        company_name = company or str(existing.get("company_name", "") if existing else "")
        jobs_by_id[job_id] = {
            "company_name": company_name,
            "title": title,
            "url": full_url,
            "external_url": full_url,
            "source_platform": "jobkorea",
            "source_record_id": job_id,
            "posted_date": "",
            "deadline": deadline,
            "field": "",
            "employment_type": employment_type,
            "career_type": career_type,
            "location": location,
            "raw_data": {
                "sourcePlatform": "jobkorea",
                "jobkoreaId": job_id,
                "href": full_url,
                "tags": tags,
            },
        }

    parser = JobKoreaLinkParser()
    parser.feed(html_text)
    for link in parser.links:
        if len(jobs_by_id) >= max_items:
            break
        job_id = extract_jobkorea_id(link["href"])
        if not job_id or job_id in jobs_by_id:
            continue
        full_url = urllib.parse.urljoin(base_url, html.unescape(link["href"]))
        full_url = normalize_jobkorea_url(full_url)
        company, title = parse_jobkorea_onclick(link.get("onclick", ""))
        anchor_text = clean_text(link.get("text", ""))
        if not title and anchor_text and not looks_like_company_logo(anchor_text):
            title = anchor_text
        title, title_deadline = clean_title(title)
        if not title or not looks_like_job_title(title):
            continue
        jobs_by_id[job_id] = {
            "company_name": company,
            "title": title,
            "url": full_url,
            "external_url": full_url,
            "source_platform": "jobkorea",
            "source_record_id": job_id,
            "posted_date": "",
            "deadline": title_deadline,
            "field": "",
            "employment_type": derive_employment_type([title]),
            "career_type": derive_career_type([title]),
            "location": "",
            "raw_data": {
                "sourcePlatform": "jobkorea",
                "jobkoreaId": job_id,
                "href": full_url,
                "anchorText": anchor_text,
                "parser": "link_fallback",
            },
        }

    jobs = list(jobs_by_id.values())[:max_items]
    for job in jobs:
        job["unique_key"] = unique_key(job)
    return jobs


def parse_saramin_jobs(html_text: str, *, base_url: str, max_items: int) -> list[dict[str, Any]]:
    jobs_by_id: dict[str, dict[str, Any]] = {}
    for block in extract_list_blocks(html_text, "item"):
        href = first_match(block, r'href=["\']([^"\']*rec_idx=\d+[^"\']*)["\']')
        job_id = extract_saramin_id(href)
        if not job_id:
            continue
        full_url = normalize_saramin_url(job_id)
        title = strip_tags(first_match(block, r'<strong class="tit">(.*?)</strong>'))
        title = title or clean_text(
            first_match(block, r'<a[^>]+rec_idx=\d+[^>]+title=["\']([^"\']+)["\']')
        )
        title, title_deadline = clean_title(title)
        if title in UI_BUTTON_TEXTS:
            title = ""
        company = strip_tags(first_match(block, r'<span class="corp">(.*?)</span>'))
        company = company or clean_text(
            first_match(block, r'<span class="logo">\s*<img[^>]+alt=["\']([^"\']+)["\']')
        )
        desc_html = first_match(block, r'<ul class="desc">(.*?)</ul>')
        desc_items = [
            strip_tags(item)
            for item in re.findall(r'<li(?:\s+[^>]*)?>(.*?)</li>', desc_html, flags=re.S)
        ]
        deadline = strip_tags(first_match(block, r'<span class="date[^"]*">(.*?)</span>'))
        deadline = deadline or title_deadline
        career_type = derive_career_type(desc_items + [title])
        employment_type = derive_employment_type(desc_items + [title])
        location = first_location_tag(desc_items)
        if not title:
            continue
        jobs_by_id[job_id] = {
            "company_name": company,
            "title": title,
            "url": full_url,
            "external_url": full_url,
            "source_platform": "saramin",
            "source_record_id": job_id,
            "posted_date": "",
            "deadline": deadline,
            "field": "",
            "employment_type": employment_type,
            "career_type": career_type,
            "location": location,
            "raw_data": {
                "sourcePlatform": "saramin",
                "saraminId": job_id,
                "href": full_url,
                "desc": desc_items,
            },
        }

    jobs = list(jobs_by_id.values())[:max_items]
    for job in jobs:
        job["unique_key"] = unique_key(job)
    return jobs


class JobKoreaLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        href = attr_map.get("href", "")
        if "/recruit/gi_read/" not in href.lower():
            return
        self._current = {"href": href, "onclick": attr_map.get("onclick", "")}
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current is None:
            return
        self._current["text"] = clean_text(" ".join(self._text_parts))
        self.links.append(self._current)
        self._current = None
        self._text_parts = []


UI_BUTTON_TEXTS = frozenset(
    {
        "스크랩",
        "관심등록",
        "관심기업 등록하기",
        "입사지원",
        "즉시지원",
        "즐겨찾기",
        "채용정보 스크랩하기",
    }
)

TRAILING_DEADLINE_PATTERN = re.compile(
    r"\s*(~\s*\d{1,2}[./]\d{1,2}(?:\([^)]*\))?|상시\s*채용|채용\s*시\s*마감|오늘\s*마감|내일\s*마감|D-\d+)\s*$"
)


def clean_title(value: str) -> tuple[str, str]:
    """제목 끝에 붙은 마감 표기를 떼어내고 (제목, 마감일) 튜플로 돌려준다."""
    title = clean_text(value)
    deadline = ""
    match = TRAILING_DEADLINE_PATTERN.search(title)
    if match:
        deadline = match.group(1).strip()
        title = title[: match.start()].rstrip()
    title = re.sub(r"\s*\.{2,}$", "", title)
    return title, deadline


def normalize_saramin_url(job_id: str) -> str:
    return f"https://www.saramin.co.kr/zf_user/jobs/view?rec_idx={job_id}"


def extract_jobkorea_id(url: str) -> str:
    match = re.search(r"/Recruit/GI_Read/(\d+)", url, flags=re.I)
    return match.group(1) if match else ""


def extract_saramin_id(url: str) -> str:
    match = re.search(r"rec_idx=(\d+)", html.unescape(url), flags=re.I)
    return match.group(1) if match else ""


def normalize_jobkorea_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def parse_jobkorea_onclick(value: str) -> tuple[str, str]:
    if not value:
        return "", ""
    quoted = re.findall(r"'([^']+)'", html.unescape(value))
    if not quoted:
        return "", ""
    label = quoted[-1]
    if "_" not in label:
        return "", clean_text(label)
    company, title = label.split("_", 1)
    return clean_text(company), clean_text(title)


def looks_like_company_logo(value: str) -> bool:
    return "썸네일" in value or value.lower().endswith("logo")


def looks_like_job_title(value: str) -> bool:
    if len(value) >= 16:
        return True
    tokens = (
        "채용",
        "모집",
        "신입",
        "경력",
        "인턴",
        "엔지니어",
        "기계",
        "생산",
        "설비",
        "공정",
        "품질",
        "안전",
        "정비",
        "개발",
        "설계",
    )
    return any(token in value for token in tokens)


def extract_list_blocks(html_text: str, class_token: str) -> list[str]:
    pattern = re.compile(r'<li\b(?=[^>]*class=["\'][^"\']*\b' + re.escape(class_token) + r'\b)', re.I)
    starts = [match.start() for match in pattern.finditer(html_text)]
    blocks = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else find_enclosing_ul_end(html_text, start)
        if end == -1:
            end = min(len(html_text), start + 12000)
        blocks.append(html_text[start:end])
    return blocks


def find_enclosing_ul_end(html_text: str, start: int) -> int:
    """start 위치의 <li>가 속한 <ul>이 닫히는 지점을 찾는다. 중첩 <ul>은 건너뛴다."""
    depth = 0
    for match in re.finditer(r"<ul\b|</ul>", html_text[start:], flags=re.I):
        if match.group(0).lower().startswith("<ul"):
            depth += 1
        elif depth == 0:
            return start + match.start()
        else:
            depth -= 1
    return -1


def first_match(value: str, pattern: str) -> str:
    match = re.search(pattern, value, flags=re.I | re.S)
    return match.group(1) if match else ""


def strip_tags(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", value))


def first_matching_tag(values: list[str], keywords: tuple[str, ...]) -> str:
    for value in values:
        for keyword in keywords:
            if keyword in value:
                return value
    return ""


def first_location_tag(values: list[str]) -> str:
    locations = (
        "서울",
        "경기",
        "인천",
        "대전",
        "대구",
        "부산",
        "광주",
        "울산",
        "세종",
        "강원",
        "충북",
        "충남",
        "전북",
        "전남",
        "경북",
        "경남",
        "제주",
        "해외",
        "전국",
    )
    return first_matching_tag(values, locations)


def derive_career_type(values: list[str]) -> str:
    joined = " ".join(values)
    if "경력무관" in joined:
        return "경력무관"
    has_new = "신입" in joined
    has_career = "경력" in joined or re.search(r"\d+\s*년", joined) is not None
    has_intern = "인턴" in joined
    parts = []
    if has_new:
        parts.append("신입")
    if has_career:
        parts.append("경력")
    if has_intern:
        parts.append("인턴")
    return "/".join(dict.fromkeys(parts))


def derive_employment_type(values: list[str]) -> str:
    joined = " ".join(values)
    keywords = ("정규직", "계약직", "인턴", "프리랜서", "파견직", "위촉직")
    return "/".join(keyword for keyword in keywords if keyword in joined)


def clean_text(value: str) -> str:
    return " ".join(html.unescape(value).split())


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
