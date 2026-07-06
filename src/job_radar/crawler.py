from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import urllib.parse

from .alio_client import AlioPublicClient, normalize_record
from .company_client import fetch_company_jobs, load_company_targets
from .company_watchlist import CompanyWatchlist, load_company_watchlist, tag_watchlist_jobs
from .config import Settings
from .db import (
    ensure_alio_source,
    ensure_source,
    insert_jobs,
    log_crawl,
    mark_source_failure,
    mark_source_success,
)
from .jasoseol_client import JASOSEOL_API_URL, fetch_jasoseol_jobs
from .platform_client import RobotsBlockedError, fetch_platform_jobs
from .scoring import score_job
from .worknet_client import fetch_worknet_jobs


# 잡코리아 기계·설비 계열 직무 카테고리 목록 페이지
DEFAULT_JOBKOREA_URLS = [
    "https://www.jobkorea.co.kr/recruit/joblist?menucode=duty&duty=1000327",
    "https://www.jobkorea.co.kr/recruit/joblist?menucode=duty&duty=1000329",
    "https://www.jobkorea.co.kr/recruit/joblist?menucode=duty&duty=1000330",
    "https://www.jobkorea.co.kr/recruit/joblist?menucode=duty&duty=1000332",
    "https://www.jobkorea.co.kr/recruit/joblist?menucode=duty&duty=10041",
]

# 사람인 직종 중분류: 11=생산(기계·설비 포함), 9=연구·R&D
DEFAULT_SARAMIN_URLS = [
    "https://www.saramin.co.kr/zf_user/jobs/list/job-category?cat_mcls=11",
    "https://www.saramin.co.kr/zf_user/jobs/list/job-category?cat_mcls=9",
]

# 목록 페이지가 어떤 직무 카테고리인지 — 분류(기계직/참고/무관)의 소스 신호로 사용
LIST_CATEGORIES = {
    "jobkorea": {
        "duty=1000327": "기계 직무 목록",
        "duty=1000329": "기계 직무 목록",
        "duty=1000330": "기계 직무 목록",
        "duty=1000332": "기계 직무 목록",
        "duty=10041": "기계 직무 목록",
    },
    "saramin": {
        "cat_mcls=11": "생산 직무 목록",
        "cat_mcls=9": "연구 직무 목록",
    },
}


def list_category_for(platform: str, url: str) -> str:
    for token, label in LIST_CATEGORIES.get(platform, {}).items():
        if token in url:
            return label
    return ""


def tag_list_category(jobs: list[dict[str, Any]], platform: str, url: str) -> None:
    category = list_category_for(platform, url)
    if not category:
        return
    for job in jobs:
        raw = job.setdefault("raw_data", {})
        if isinstance(raw, dict):
            raw["listCategory"] = category


@dataclass
class CrawlRunResult:
    fetched: int = 0
    candidates: int = 0
    inserted: int = 0
    errors: list[str] | None = None

    def add_error(self, message: str) -> None:
        if self.errors is None:
            self.errors = []
        self.errors.append(message)


def score_jobs(
    jobs: list[dict[str, Any]],
    rules: dict[str, list[dict[str, Any]]],
    watchlist: CompanyWatchlist | None = None,
) -> list[dict[str, Any]]:
    scored = []
    for job in jobs:
        score, matched = score_job(job, rules)
        job["score"] = score
        job["matched_keywords"] = matched
        scored.append(job)
    tag_watchlist_jobs(scored, watchlist)
    scored.sort(key=lambda item: int(item.get("score", 0)), reverse=True)
    return scored


def run_all_crawlers(
    conn: Any,
    *,
    settings: Settings,
    rules: dict[str, list[dict[str, Any]]],
    platform_max_items: int = 1000,
    platform_max_pages: int = 5,
    platform_min_score: int = -999,
    worknet_max_pages: int = 20,
) -> CrawlRunResult:
    result = CrawlRunResult(errors=[])
    watchlist = load_company_watchlist()
    result = run_alio_public(conn, settings=settings, rules=rules, result=result, watchlist=watchlist)
    result = run_platform(
        conn,
        platform="jobkorea",
        urls=DEFAULT_JOBKOREA_URLS,
        rules=rules,
        result=result,
        watchlist=watchlist,
        max_items=platform_max_items,
        max_pages=platform_max_pages,
        min_score=platform_min_score,
    )
    result = run_platform(
        conn,
        platform="saramin",
        urls=DEFAULT_SARAMIN_URLS,
        rules=rules,
        result=result,
        watchlist=watchlist,
        max_items=platform_max_items,
        max_pages=platform_max_pages,
        min_score=platform_min_score,
    )
    result = run_jasoseol(
        conn,
        rules=rules,
        result=result,
        watchlist=watchlist,
        max_items=platform_max_items,
        max_pages=platform_max_pages * 2,
    )
    result = run_company_targets(
        conn,
        settings=settings,
        rules=rules,
        result=result,
        watchlist=watchlist,
        max_items=platform_max_items,
        min_score=platform_min_score,
    )
    result = run_worknet(
        conn,
        settings=settings,
        rules=rules,
        result=result,
        watchlist=watchlist,
        max_pages=worknet_max_pages,
    )
    return result


def run_company_targets(
    conn: Any,
    *,
    settings: Settings,
    rules: dict[str, list[dict[str, Any]]],
    result: CrawlRunResult,
    watchlist: CompanyWatchlist,
    max_items: int,
    min_score: int,
) -> CrawlRunResult:
    for target in load_company_targets(settings.company_targets_path):
        source_id = ensure_source(conn, url=target.url, platform="company", source_type="company")
        try:
            fetch = fetch_company_jobs(target, max_items=max_items)
            jobs = score_jobs(fetch.jobs, rules, watchlist)
            candidates = [job for job in jobs if int(job.get("score", 0)) >= min_score]
            inserted = insert_jobs(conn, candidates, source_id)
            log_crawl(
                conn,
                source_id=source_id,
                status="company_success",
                new_jobs_count=inserted,
                duration_ms=fetch.duration_ms,
            )
            mark_source_success(conn, source_id)
            result.fetched += len(fetch.jobs)
            result.candidates += len(candidates)
            result.inserted += inserted
        except RobotsBlockedError as exc:
            mark_source_failure(conn, source_id)
            log_crawl(conn, source_id=source_id, status="company_blocked", error_message=str(exc))
            result.add_error(f"{target.name}: {exc}")
        except Exception as exc:
            mark_source_failure(conn, source_id)
            log_crawl(conn, source_id=source_id, status="company_fail", error_message=str(exc))
            result.add_error(f"{target.name}: {exc}")
    return result


def run_alio_public(
    conn: Any,
    *,
    settings: Settings,
    rules: dict[str, list[dict[str, Any]]],
    result: CrawlRunResult,
    watchlist: CompanyWatchlist,
) -> CrawlRunResult:
    if not settings.alio_public_enabled or not settings.alio_public_url:
        return result
    for params in expand_alio_public_params(settings.alio_public_default_params):
        ncs_code = params.get("ncsCdLst", "")
        source_url = f"{settings.alio_public_url}?ncsCdLst={ncs_code}" if ncs_code else settings.alio_public_url
        source_id = ensure_alio_source(conn, source_url)
        try:
            client = AlioPublicClient(
                url=settings.alio_public_url,
                default_params=params,
            )
            fetch = client.fetch()
            jobs = []
            for record in fetch.records:
                job = normalize_record(record)
                jobs.append(job)
            jobs = score_jobs(jobs, rules, watchlist)
            inserted = insert_jobs(conn, jobs, source_id)
            log_crawl(
                conn,
                source_id=source_id,
                status="public_success",
                new_jobs_count=inserted,
                duration_ms=fetch.duration_ms,
            )
            mark_source_success(conn, source_id)
            result.fetched += len(fetch.records)
            result.candidates += len(jobs)
            result.inserted += inserted
        except Exception as exc:
            mark_source_failure(conn, source_id)
            log_crawl(conn, source_id=source_id, status="public_fail", error_message=str(exc))
            result.add_error(f"ALIO {ncs_code or 'default'}: {exc}")
    return result


def expand_alio_public_params(params: dict[str, str]) -> list[dict[str, str]]:
    ncs_value = params.get("ncsCdLst", "")
    codes = [
        item.strip()
        for item in ncs_value.replace("|", ",").replace(";", ",").split(",")
        if item.strip()
    ]
    if len(codes) <= 1:
        return [params]
    expanded = []
    for code in codes:
        item = dict(params)
        item["ncsCdLst"] = code
        expanded.append(item)
    return expanded


def run_platform(
    conn: Any,
    *,
    platform: str,
    urls: list[str],
    rules: dict[str, list[dict[str, Any]]],
    result: CrawlRunResult,
    watchlist: CompanyWatchlist,
    max_items: int,
    max_pages: int,
    min_score: int,
) -> CrawlRunResult:
    for url in expand_platform_urls(platform, urls, max_pages=max_pages):
        source_id = ensure_source(conn, url=url, platform=platform, source_type="platform")
        try:
            fetch = fetch_platform_jobs(platform=platform, url=url, max_items=max_items)
            tag_list_category(fetch.jobs, platform, url)
            jobs = score_jobs(fetch.jobs, rules, watchlist)
            candidates = [job for job in jobs if int(job.get("score", 0)) >= min_score]
            inserted = insert_jobs(conn, candidates, source_id)
            log_crawl(
                conn,
                source_id=source_id,
                status="platform_success",
                new_jobs_count=inserted,
                duration_ms=fetch.duration_ms,
            )
            mark_source_success(conn, source_id)
            result.fetched += len(fetch.jobs)
            result.candidates += len(candidates)
            result.inserted += inserted
        except RobotsBlockedError as exc:
            mark_source_failure(conn, source_id)
            log_crawl(conn, source_id=source_id, status="platform_blocked", error_message=str(exc))
            result.add_error(f"{platform}: {exc}")
        except Exception as exc:
            mark_source_failure(conn, source_id)
            log_crawl(conn, source_id=source_id, status="platform_fail", error_message=str(exc))
            result.add_error(f"{platform}: {exc}")
    return result


def expand_platform_urls(platform: str, urls: list[str], *, max_pages: int) -> list[str]:
    if max_pages <= 1:
        return urls
    expanded: list[str] = []
    for url in urls:
        for page in range(1, max_pages + 1):
            expanded.append(with_page_param(platform, url, page))
    return list(dict.fromkeys(expanded))


def with_page_param(platform: str, url: str, page: int) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    if platform == "jobkorea":
        query["Page_No"] = str(page)
    elif platform == "saramin":
        query["recruitPage"] = str(page)
    else:
        return url
    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urllib.parse.urlencode(query),
            parsed.fragment,
        )
    )


def run_jasoseol(
    conn: Any,
    *,
    rules: dict[str, list[dict[str, Any]]],
    result: CrawlRunResult,
    watchlist: CompanyWatchlist,
    max_items: int,
    max_pages: int,
) -> CrawlRunResult:
    source_id = ensure_source(conn, url=JASOSEOL_API_URL, platform="jasoseol", source_type="api")
    try:
        fetch = fetch_jasoseol_jobs(max_items=max_items, max_pages=max_pages)
        jobs = score_jobs(fetch.jobs, rules, watchlist)
        inserted = insert_jobs(conn, jobs, source_id)
        log_crawl(
            conn,
            source_id=source_id,
            status="jasoseol_success",
            new_jobs_count=inserted,
            duration_ms=fetch.duration_ms,
        )
        mark_source_success(conn, source_id)
        result.fetched += len(fetch.jobs)
        result.candidates += len(jobs)
        result.inserted += inserted
    except RobotsBlockedError as exc:
        mark_source_failure(conn, source_id)
        log_crawl(conn, source_id=source_id, status="jasoseol_blocked", error_message=str(exc))
        result.add_error(f"jasoseol: {exc}")
    except Exception as exc:
        mark_source_failure(conn, source_id)
        log_crawl(conn, source_id=source_id, status="jasoseol_fail", error_message=str(exc))
        result.add_error(f"jasoseol: {exc}")
    return result


def run_worknet(
    conn: Any,
    *,
    settings: Settings,
    rules: dict[str, list[dict[str, Any]]],
    result: CrawlRunResult,
    watchlist: CompanyWatchlist,
    max_pages: int,
) -> CrawlRunResult:
    if not settings.worknet_enabled or not settings.worknet_api_key:
        return result
    source_id = ensure_source(
        conn,
        url=settings.worknet_api_url,
        platform="worknet",
        source_type="api",
    )
    try:
        fetch = fetch_worknet_jobs(
            api_url=settings.worknet_api_url,
            api_key=settings.worknet_api_key,
            keywords=settings.worknet_keywords,
            occupations=settings.worknet_occupations,
            max_pages=max_pages,
        )
        jobs = score_jobs(fetch.jobs, rules, watchlist)
        inserted = insert_jobs(conn, jobs, source_id)
        log_crawl(
            conn,
            source_id=source_id,
            status="worknet_success",
            new_jobs_count=inserted,
            duration_ms=fetch.duration_ms,
        )
        mark_source_success(conn, source_id)
        result.fetched += len(fetch.jobs)
        result.candidates += len(jobs)
        result.inserted += inserted
    except Exception as exc:
        mark_source_failure(conn, source_id)
        log_crawl(conn, source_id=source_id, status="worknet_fail", error_message=str(exc))
        result.add_error(f"Worknet: {exc}")
    return result
