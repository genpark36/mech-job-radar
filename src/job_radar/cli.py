from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .alio_client import AlioClient, AlioPublicClient, extract_records, normalize_record, parse_response
from .company_client import fetch_company_jobs, load_company_targets
from .company_registry import set_company_link, write_registry_files
from .company_watchlist import (
    DEFAULT_WATCHLIST_PATH,
    load_company_watchlist,
    tag_watchlist_jobs,
    write_company_watchlist,
)
from .config import load_keywords, load_settings
from .crawler import (
    DEFAULT_JOBKOREA_URLS,
    DEFAULT_SARAMIN_URLS,
    expand_platform_urls,
    run_all_crawlers,
)
from .dashboard import write_dashboard
from .db import (
    cleanup_jobs,
    connect,
    dashboard_summary,
    ensure_alio_source,
    ensure_source,
    init_db,
    insert_jobs,
    list_jobs,
    list_logs,
    list_source_health,
    log_crawl,
    mark_source_failure,
    mark_source_success,
    seed_keywords,
)
from .jasoseol_client import JASOSEOL_API_URL, fetch_jasoseol_jobs
from .link_discovery import DiscoveryOptions, discover_company_links
from .notifier import build_message, send_telegram
from .platform_client import RobotsBlockedError, fetch_platform_jobs
from .scoring import score_job
from .server import run_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job_radar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create SQLite schema and seed keyword rules.")
    subparsers.add_parser("check-config", help="Print ALIO/DB configuration without exposing secrets.")

    fetch_parser = subparsers.add_parser("fetch-alio", help="Fetch ALIO recruitment records.")
    fetch_parser.add_argument("--dry-run", action="store_true", help="Do not write records to DB.")
    fetch_parser.add_argument("--limit", type=int, default=0, help="Print at most N normalized jobs.")
    fetch_parser.add_argument(
        "--notify",
        action="store_true",
        help="Send Telegram notifications for newly inserted jobs with score >= threshold.",
    )
    fetch_parser.add_argument("--notify-threshold", type=int, default=12)
    fetch_parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Extra ALIO API query parameter as key=value. Can be repeated.",
    )

    public_parser = subparsers.add_parser(
        "fetch-alio-public",
        help="Fetch public ALIO recruitment records from the public lookup endpoint.",
    )
    public_parser.add_argument("--dry-run", action="store_true")
    public_parser.add_argument("--limit", type=int, default=5)
    public_parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Extra public lookup form parameter as key=value. Can be repeated.",
    )

    platform_parser = subparsers.add_parser(
        "fetch-platform",
        help="Fetch public recruitment list pages from allowed platform paths.",
    )
    platform_parser.add_argument(
        "--platform", default="jobkorea", choices=["jobkorea", "saramin", "jasoseol"]
    )
    platform_parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Public list URL to crawl. Can be repeated. Defaults to JobKorea joblist.",
    )
    platform_parser.add_argument("--dry-run", action="store_true")
    platform_parser.add_argument("--limit", type=int, default=10)
    platform_parser.add_argument("--max-items", type=int, default=1000)
    platform_parser.add_argument("--max-pages", type=int, default=5)
    platform_parser.add_argument(
        "--min-score",
        type=int,
        default=-999,
        help="Store only jobs with score >= N. Default stores every parsed platform job.",
    )

    all_parser = subparsers.add_parser("fetch-all", help="Fetch ALIO, platform, and Worknet sources.")
    all_parser.add_argument("--platform-max-items", type=int, default=1000)
    all_parser.add_argument("--platform-max-pages", type=int, default=5)
    all_parser.add_argument("--platform-min-score", type=int, default=-999)
    all_parser.add_argument("--worknet-max-pages", type=int, default=20)

    company_parser = subparsers.add_parser(
        "fetch-company",
        help="Fetch configured company career pages with the generic direct-source parser.",
    )
    company_parser.add_argument("--dry-run", action="store_true")
    company_parser.add_argument("--limit", type=int, default=10)
    company_parser.add_argument("--max-items", type=int, default=100)
    company_parser.add_argument("--min-score", type=int, default=-999)
    company_parser.add_argument(
        "--name",
        action="append",
        default=[],
        help="Only crawl matching company name. Can be repeated.",
    )

    import_company_parser = subparsers.add_parser(
        "import-company-xlsx",
        help="Import the mechanical company XLSX into registry and link queue JSON files.",
    )
    import_company_parser.add_argument("path", help="XLSX file path.")
    import_company_parser.add_argument("--grades", default="A,B", help="Comma-separated watch grades.")
    import_company_parser.add_argument("--limit", type=int, default=0, help="0 means no limit.")
    import_company_parser.add_argument(
        "--registry-output",
        default="config/company_registry.json",
    )
    import_company_parser.add_argument(
        "--queue-output",
        default="config/company_link_queue.json",
    )

    watchlist_parser = subparsers.add_parser(
        "import-company-watchlist",
        help="Import the XLSX into a full A-D company watchlist for platform matching.",
    )
    watchlist_parser.add_argument("path", help="XLSX file path.")
    watchlist_parser.add_argument("--grades", default="A,B,C,D", help="Comma-separated watch grades.")
    watchlist_parser.add_argument("--limit", type=int, default=0, help="0 means no limit.")
    watchlist_parser.add_argument("--output", default=str(DEFAULT_WATCHLIST_PATH))

    subparsers.add_parser(
        "tag-existing-watchlist",
        help="Apply company watchlist tags to already stored detected jobs.",
    )

    link_parser = subparsers.add_parser(
        "set-company-link",
        help="Add or update one company recruitment URL in company_targets.json.",
    )
    link_parser.add_argument("--name", required=True)
    link_parser.add_argument("--url", required=True)
    link_parser.add_argument("--parser", default="")
    link_parser.add_argument("--enable", action="store_true", help="Enable this target immediately.")

    queue_parser = subparsers.add_parser(
        "company-link-queue",
        help="Print companies that still need recruitment URL linking.",
    )
    queue_parser.add_argument("--path", default="config/company_link_queue.json")
    queue_parser.add_argument("--limit", type=int, default=20)
    queue_parser.add_argument("--search", default="", help="Filter by company/industry/role text.")
    queue_parser.add_argument("--grade", default="", help="Comma-separated watch grades, e.g. A,B.")

    discover_parser = subparsers.add_parser(
        "discover-company-links",
        help="Build candidate recruitment URLs from the company link queue.",
    )
    discover_parser.add_argument("--queue", default="config/company_link_queue.json")
    discover_parser.add_argument("--output", default="config/company_link_candidates.json")
    discover_parser.add_argument("--provider", default="auto", choices=["auto", "generated", "brave"])
    discover_parser.add_argument("--limit", type=int, default=20)
    discover_parser.add_argument("--grade", default="", help="Comma-separated watch grades, e.g. A,B.")
    discover_parser.add_argument("--search", default="", help="Filter by company/industry/role text.")
    discover_parser.add_argument("--per-company", type=int, default=8)
    discover_parser.add_argument("--delay", type=float, default=1.0)

    candidates_parser = subparsers.add_parser(
        "company-link-candidates",
        help="Print discovered recruitment URL candidates.",
    )
    candidates_parser.add_argument("--path", default="config/company_link_candidates.json")
    candidates_parser.add_argument("--limit", type=int, default=20)
    candidates_parser.add_argument("--per-company", type=int, default=5)
    candidates_parser.add_argument("--min-score", type=int, default=-999)

    sample_parser = subparsers.add_parser("import-sample", help="Import a local ALIO-like JSON/XML sample.")
    sample_parser.add_argument("path", help="Sample response path.")
    sample_parser.add_argument("--dry-run", action="store_true")
    sample_parser.add_argument("--limit", type=int, default=5)

    cleanup_parser = subparsers.add_parser(
        "cleanup-jobs",
        help="Delete rows with UI-button titles or platform fallback company names.",
    )
    cleanup_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete/update rows. Default only prints counts.",
    )

    jobs_parser = subparsers.add_parser("list-jobs", help="Print recent detected jobs.")
    jobs_parser.add_argument("--limit", type=int, default=20)
    jobs_parser.add_argument("--min-score", type=int)

    logs_parser = subparsers.add_parser("logs", help="Print recent crawl logs.")
    logs_parser.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("audit-sources", help="Print configured company targets and DB source health.")

    dash_parser = subparsers.add_parser("write-dashboard", help="Write a static HTML dashboard.")
    dash_parser.add_argument("--output", default="data/dashboard.html")
    dash_parser.add_argument("--limit", type=int, default=0, help="0 means all jobs.")

    serve_parser = subparsers.add_parser("serve", help="Run live dashboard with 6-hour KST auto crawl.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8787)
    serve_parser.add_argument("--no-run-on-start", action="store_true")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "init-db":
        with connect(settings.db_path) as conn:
            init_db(conn)
            seeded = seed_keywords(conn, load_keywords())
        print(f"Initialized DB: {settings.db_path}")
        print(f"Seeded keyword rules: {seeded}")
        return 0
    if args.command == "check-config":
        return check_config()

    if args.command == "fetch-alio":
        return fetch_alio(args)
    if args.command == "fetch-alio-public":
        return fetch_alio_public(args)
    if args.command == "fetch-platform":
        return fetch_platform(args)
    if args.command == "fetch-company":
        return fetch_company(args)
    if args.command == "import-company-xlsx":
        return import_company_xlsx(args)
    if args.command == "import-company-watchlist":
        return import_company_watchlist(args)
    if args.command == "tag-existing-watchlist":
        return tag_existing_watchlist_command()
    if args.command == "set-company-link":
        return set_company_link_command(args)
    if args.command == "company-link-queue":
        return print_company_link_queue(args)
    if args.command == "discover-company-links":
        return discover_company_links_command(args)
    if args.command == "company-link-candidates":
        return print_company_link_candidates(args)
    if args.command == "fetch-all":
        return fetch_all(args)
    if args.command == "import-sample":
        return import_sample(args)
    if args.command == "cleanup-jobs":
        return cleanup_jobs_command(args)
    if args.command == "list-jobs":
        return print_jobs(args)
    if args.command == "logs":
        return print_logs(args)
    if args.command == "audit-sources":
        return audit_sources()
    if args.command == "write-dashboard":
        return render_dashboard_file(args)
    if args.command == "serve":
        run_server(host=args.host, port=args.port, run_on_start=not args.no_run_on_start)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def fetch_alio(args: argparse.Namespace) -> int:
    settings = load_settings()
    rules = load_keywords()
    source_id: int | None = None

    with connect(settings.db_path) as conn:
        init_db(conn)
        if settings.alio_api_url:
            source_id = ensure_alio_source(conn, settings.alio_api_url)

        try:
            client = AlioClient(
                api_url=settings.alio_api_url,
                api_key=settings.alio_api_key,
                api_key_param=settings.alio_api_key_param,
                default_params=settings.alio_default_params,
            )
            result = client.fetch(extra_params=parse_extra_params(args.param))
            jobs = normalize_and_score(result.records, rules)

            if args.limit:
                for job in jobs[: args.limit]:
                    print_job(job)

            if args.dry_run:
                print(f"Fetched records: {len(result.records)}")
                print(f"Normalized jobs: {len(jobs)}")
                print("Dry-run: DB insert skipped.")
                log_crawl(
                    conn,
                    source_id=source_id,
                    status="success_dry_run",
                    new_jobs_count=0,
                    duration_ms=result.duration_ms,
                )
                mark_source_success(conn, source_id)
                print(f"Content-Type: {result.content_type or 'unknown'}")
                print(f"Request URL: {result.request_url}")
                return 0

            new_count = insert_jobs(conn, jobs, source_id or 0)
            log_crawl(
                conn,
                source_id=source_id,
                status="success",
                new_jobs_count=new_count,
                duration_ms=result.duration_ms,
            )
            mark_source_success(conn, source_id)
            print(f"Fetched records: {len(result.records)}")
            print(f"Inserted new jobs: {new_count}")
            print(f"Content-Type: {result.content_type or 'unknown'}")
            print(f"Request URL: {result.request_url}")

            if args.notify and new_count:
                send_notifications(settings, jobs, args.notify_threshold)
            return 0
        except Exception as exc:
            mark_source_failure(conn, source_id)
            log_crawl(
                conn,
                source_id=source_id,
                status="fail",
                error_message=str(exc),
            )
            print(f"ALIO fetch failed: {exc}", file=sys.stderr)
            return 1


def fetch_alio_public(args: argparse.Namespace) -> int:
    settings = load_settings()
    rules = load_keywords()
    source_id: int | None = None

    with connect(settings.db_path) as conn:
        init_db(conn)
        if settings.alio_public_url:
            source_id = ensure_alio_source(conn, settings.alio_public_url)
        try:
            client = AlioPublicClient(
                url=settings.alio_public_url,
                default_params=settings.alio_public_default_params,
            )
            result = client.fetch(extra_params=parse_extra_params(args.param))
            jobs = normalize_and_score(result.records, rules)

            if args.limit:
                for job in jobs[: args.limit]:
                    print_job(job)

            if args.dry_run:
                log_crawl(
                    conn,
                    source_id=source_id,
                    status="public_success_dry_run",
                    new_jobs_count=0,
                    duration_ms=result.duration_ms,
                )
                mark_source_success(conn, source_id)
                print(f"Fetched public records: {len(result.records)}")
                print(f"Normalized jobs: {len(jobs)}")
                print(f"Content-Type: {result.content_type or 'unknown'}")
                print(f"Request: {result.request_url}")
                print("Dry-run: DB insert skipped.")
                return 0

            new_count = insert_jobs(conn, jobs, source_id or 0)
            log_crawl(
                conn,
                source_id=source_id,
                status="public_success",
                new_jobs_count=new_count,
                duration_ms=result.duration_ms,
            )
            mark_source_success(conn, source_id)
            print(f"Fetched public records: {len(result.records)}")
            print(f"Inserted new jobs: {new_count}")
            print(f"Content-Type: {result.content_type or 'unknown'}")
            print(f"Request: {result.request_url}")
            return 0
        except Exception as exc:
            mark_source_failure(conn, source_id)
            log_crawl(conn, source_id=source_id, status="public_fail", error_message=str(exc))
            print(f"ALIO public fetch failed: {exc}", file=sys.stderr)
            return 1


def normalize_and_score(
    records: list[dict[str, Any]],
    rules: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    jobs = []
    for record in records:
        job = normalize_record(record)
        score, matched = score_job(job, rules)
        job["score"] = score
        job["matched_keywords"] = matched
        jobs.append(job)
    tag_watchlist_jobs(jobs, load_company_watchlist())
    jobs.sort(key=lambda item: int(item.get("score", 0)), reverse=True)
    return jobs


def score_existing_jobs(
    jobs: list[dict[str, Any]],
    rules: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    scored = []
    for job in jobs:
        score, matched = score_job(job, rules)
        job["score"] = score
        job["matched_keywords"] = matched
        scored.append(job)
    tag_watchlist_jobs(scored, load_company_watchlist())
    scored.sort(key=lambda item: int(item.get("score", 0)), reverse=True)
    return scored


def fetch_platform(args: argparse.Namespace) -> int:
    if args.platform == "jasoseol":
        return fetch_jasoseol(args)
    settings = load_settings()
    rules = load_keywords()
    urls = expand_platform_urls(
        args.platform,
        args.url or default_platform_urls(args.platform),
        max_pages=args.max_pages,
    )
    total_fetched = 0
    total_candidates = 0
    total_inserted = 0
    had_error = False

    with connect(settings.db_path) as conn:
        init_db(conn)
        for url in urls:
            source_id = ensure_source(conn, url=url, platform=args.platform, source_type="platform")
            try:
                result = fetch_platform_jobs(
                    platform=args.platform,
                    url=url,
                    max_items=args.max_items,
                )
                jobs = score_existing_jobs(result.jobs, rules)
                candidates = [
                    job for job in jobs if int(job.get("score", 0)) >= int(args.min_score)
                ]
                total_fetched += len(jobs)
                total_candidates += len(candidates)

                for job in candidates[: args.limit]:
                    print_job(job)

                if args.dry_run:
                    log_crawl(
                        conn,
                        source_id=source_id,
                        status="platform_success_dry_run",
                        new_jobs_count=0,
                        duration_ms=result.duration_ms,
                    )
                    mark_source_success(conn, source_id)
                    print(f"Fetched platform jobs: {len(jobs)}")
                    print(f"Score candidates: {len(candidates)}")
                    print(f"Robots: {result.robots_url}")
                    print(f"Request: {result.request_url}")
                    print("Dry-run: DB insert skipped.")
                    continue

                new_count = insert_jobs(conn, candidates, source_id)
                total_inserted += new_count
                log_crawl(
                    conn,
                    source_id=source_id,
                    status="platform_success",
                    new_jobs_count=new_count,
                    duration_ms=result.duration_ms,
                )
                mark_source_success(conn, source_id)
                print(f"Fetched platform jobs: {len(jobs)}")
                print(f"Score candidates: {len(candidates)}")
                print(f"Inserted new jobs: {new_count}")
                print(f"Robots: {result.robots_url}")
                print(f"Request: {result.request_url}")
            except RobotsBlockedError as exc:
                had_error = True
                mark_source_failure(conn, source_id)
                log_crawl(conn, source_id=source_id, status="platform_blocked", error_message=str(exc))
                print(f"Platform crawl blocked: {exc}", file=sys.stderr)
            except Exception as exc:
                had_error = True
                mark_source_failure(conn, source_id)
                log_crawl(conn, source_id=source_id, status="platform_fail", error_message=str(exc))
                print(f"Platform crawl failed: {exc}", file=sys.stderr)

    print(f"Total fetched: {total_fetched}")
    print(f"Total candidates: {total_candidates}")
    if not args.dry_run:
        print(f"Total inserted: {total_inserted}")
    return 1 if had_error and total_fetched == 0 else 0


def cleanup_jobs_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    with connect(settings.db_path) as conn:
        init_db(conn)
        counts = cleanup_jobs(conn, apply=args.apply)
    mode = "삭제/갱신 완료" if args.apply else "드라이런 (실제 변경 없음, --apply로 실행)"
    print(f"정리 대상 — {mode}")
    print(f"- UI 버튼 제목 행: {counts['bad_title']}")
    print(f"- 플랫폼 폴백 회사명 행: {counts['fallback_company']}")
    print(f"- field 필러 문구 행: {counts['filler_field']}")
    return 0


def fetch_jasoseol(args: argparse.Namespace) -> int:
    settings = load_settings()
    rules = load_keywords()
    with connect(settings.db_path) as conn:
        init_db(conn)
        source_id = ensure_source(
            conn, url=JASOSEOL_API_URL, platform="jasoseol", source_type="api"
        )
        try:
            result = fetch_jasoseol_jobs(max_items=args.max_items, max_pages=args.max_pages)
        except Exception as exc:
            mark_source_failure(conn, source_id)
            log_crawl(conn, source_id=source_id, status="jasoseol_fail", error_message=str(exc))
            print(f"Jasoseol crawl failed: {exc}", file=sys.stderr)
            return 1
        jobs = score_existing_jobs(result.jobs, rules)
        candidates = [job for job in jobs if int(job.get("score", 0)) >= int(args.min_score)]
        for job in candidates[: args.limit]:
            print_job(job)
        if args.dry_run:
            log_crawl(
                conn,
                source_id=source_id,
                status="jasoseol_success_dry_run",
                new_jobs_count=0,
                duration_ms=result.duration_ms,
            )
            mark_source_success(conn, source_id)
            print(f"Fetched jasoseol jobs: {len(jobs)}")
            print(f"Score candidates: {len(candidates)}")
            print("Dry-run: DB insert skipped.")
            return 0
        new_count = insert_jobs(conn, candidates, source_id)
        log_crawl(
            conn,
            source_id=source_id,
            status="jasoseol_success",
            new_jobs_count=new_count,
            duration_ms=result.duration_ms,
        )
        mark_source_success(conn, source_id)
        print(f"Fetched jasoseol jobs: {len(jobs)}")
        print(f"Score candidates: {len(candidates)}")
        print(f"Inserted new jobs: {new_count}")
    return 0


def fetch_all(args: argparse.Namespace) -> int:
    settings = load_settings()
    rules = load_keywords()
    with connect(settings.db_path) as conn:
        init_db(conn)
        result = run_all_crawlers(
            conn,
            settings=settings,
            rules=rules,
            platform_max_items=args.platform_max_items,
            platform_max_pages=args.platform_max_pages,
            platform_min_score=args.platform_min_score,
            worknet_max_pages=args.worknet_max_pages,
        )
    print(f"Fetched: {result.fetched}")
    print(f"Candidates: {result.candidates}")
    print(f"Inserted: {result.inserted}")
    if result.errors:
        print("Errors:")
        for error in result.errors:
            print(f"- {error}")
    return 1 if result.errors and result.fetched == 0 else 0


def fetch_company(args: argparse.Namespace) -> int:
    settings = load_settings()
    rules = load_keywords()
    requested_names = {name.strip() for name in args.name if name.strip()}
    targets = load_company_targets(
        settings.company_targets_path,
        include_disabled=bool(requested_names),
    )
    if requested_names:
        targets = [target for target in targets if target.name in requested_names]

    total_fetched = 0
    total_candidates = 0
    total_inserted = 0
    had_error = False
    with connect(settings.db_path) as conn:
        init_db(conn)
        for target in targets:
            source_id = ensure_source(conn, url=target.url, platform="company", source_type="company")
            try:
                result = fetch_company_jobs(target, max_items=args.max_items)
                jobs = score_existing_jobs(result.jobs, rules)
                candidates = [
                    job for job in jobs if int(job.get("score", 0)) >= int(args.min_score)
                ]
                total_fetched += len(jobs)
                total_candidates += len(candidates)
                print(f"\n[{target.name}] {target.url}")
                for job in candidates[: args.limit]:
                    print_job(job)
                if args.dry_run:
                    log_crawl(
                        conn,
                        source_id=source_id,
                        status="company_success_dry_run",
                        new_jobs_count=0,
                        duration_ms=result.duration_ms,
                    )
                    mark_source_success(conn, source_id)
                    print(f"Fetched company jobs: {len(jobs)}")
                    print(f"Score candidates: {len(candidates)}")
                    print(f"Robots: {result.robots_url}")
                    print("Dry-run: DB insert skipped.")
                    continue
                new_count = insert_jobs(conn, candidates, source_id)
                total_inserted += new_count
                log_crawl(
                    conn,
                    source_id=source_id,
                    status="company_success",
                    new_jobs_count=new_count,
                    duration_ms=result.duration_ms,
                )
                mark_source_success(conn, source_id)
                print(f"Fetched company jobs: {len(jobs)}")
                print(f"Score candidates: {len(candidates)}")
                print(f"Inserted new jobs: {new_count}")
                print(f"Robots: {result.robots_url}")
            except RobotsBlockedError as exc:
                had_error = True
                mark_source_failure(conn, source_id)
                log_crawl(conn, source_id=source_id, status="company_blocked", error_message=str(exc))
                print(f"Company crawl blocked: {target.name}: {exc}", file=sys.stderr)
            except Exception as exc:
                had_error = True
                mark_source_failure(conn, source_id)
                log_crawl(conn, source_id=source_id, status="company_fail", error_message=str(exc))
                print(f"Company crawl failed: {target.name}: {exc}", file=sys.stderr)

    print(f"Total fetched: {total_fetched}")
    print(f"Total candidates: {total_candidates}")
    if not args.dry_run:
        print(f"Total inserted: {total_inserted}")
    return 1 if had_error and total_fetched == 0 else 0


def import_company_xlsx(args: argparse.Namespace) -> int:
    settings = load_settings()
    grades = {item.strip().upper() for item in args.grades.split(",") if item.strip()}
    registry_count, queue_count = write_registry_files(
        xlsx_path=args.path,
        registry_output=args.registry_output,
        queue_output=args.queue_output,
        existing_targets_path=settings.company_targets_path,
        grades=grades,
        limit=args.limit,
    )
    print(f"Imported registry companies: {registry_count}")
    print(f"Link queue items: {queue_count}")
    print(f"Registry: {args.registry_output}")
    print(f"Queue: {args.queue_output}")
    return 0


def import_company_watchlist(args: argparse.Namespace) -> int:
    grades = {item.strip().upper() for item in args.grades.split(",") if item.strip()}
    count = write_company_watchlist(
        xlsx_path=args.path,
        output_path=args.output,
        grades=grades,
        limit=args.limit,
    )
    print(f"Imported watchlist companies: {count}")
    print(f"Grades: {', '.join(sorted(grades)) if grades else 'all'}")
    print(f"Output: {args.output}")
    return 0


def tag_existing_watchlist_command() -> int:
    settings = load_settings()
    watchlist = load_company_watchlist()
    if not watchlist.companies:
        print(f"Company watchlist not found or empty: {DEFAULT_WATCHLIST_PATH}", file=sys.stderr)
        return 1
    updated = 0
    matched = 0
    with connect(settings.db_path) as conn:
        init_db(conn)
        rows = conn.execute(
            """
            SELECT id, company_name, matched_keywords, raw_data
            FROM detected_jobs
            """
        ).fetchall()
        for row in rows:
            raw_data = parse_json_object(row["raw_data"])
            keywords = normalize_matched_keywords(row["matched_keywords"])
            job = {
                "company_name": row["company_name"],
                "matched_keywords": keywords,
                "raw_data": raw_data,
            }
            tag_watchlist_jobs([job], watchlist)
            if not job.get("watch_company_name"):
                continue
            matched += 1
            new_raw = json.dumps(job.get("raw_data", {}), ensure_ascii=False)
            new_keywords = json.dumps(job.get("matched_keywords", []), ensure_ascii=False)
            if new_raw != (row["raw_data"] or "") or new_keywords != (row["matched_keywords"] or ""):
                conn.execute(
                    """
                    UPDATE detected_jobs
                    SET raw_data = ?, matched_keywords = ?
                    WHERE id = ?
                    """,
                    (new_raw, new_keywords, row["id"]),
                )
                updated += 1
        conn.commit()
    print(f"Watchlist matched jobs: {matched}")
    print(f"Updated jobs: {updated}")
    return 0


def set_company_link_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    set_company_link(
        targets_path=settings.company_targets_path,
        registry_path="config/company_registry.json",
        name=args.name,
        url=args.url,
        parser=args.parser,
        enabled=args.enable,
    )
    print(f"Updated company target: {args.name}")
    print(f"URL: {args.url}")
    print(f"Enabled: {bool(args.enable)}")
    return 0


def print_company_link_queue(args: argparse.Namespace) -> int:
    queue_path = Path(args.path)
    if not queue_path.exists():
        print(f"Queue file not found: {queue_path}", file=sys.stderr)
        return 1
    with queue_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    items = list(data.get("items", []))
    grades = {grade.strip() for grade in args.grade.split(",") if grade.strip()}
    search = str(args.search or "").strip().lower()
    if grades:
        items = [item for item in items if str(item.get("watch_grade") or "") in grades]
    if search:
        items = [
            item
            for item in items
            if search
            in " ".join(
                str(item.get(key) or "")
                for key in ("name", "industry", "mechanical_roles", "regions")
            ).lower()
        ]

    print(f"Company link queue: {len(items)}")
    for item in items[: max(args.limit, 0)]:
        searches = item.get("suggested_searches") or {}
        print("-" * 60)
        print(f"{item.get('name')} | grade={item.get('watch_grade')} | size={item.get('size_grade')}")
        print(f"industry: {item.get('industry')}")
        print(f"roles: {item.get('mechanical_roles')}")
        print(f"regions: {item.get('regions')}")
        for key in ("naver", "google", "saramin", "jobkorea"):
            if searches.get(key):
                print(f"{key}: {searches[key]}")
    if args.limit and len(items) > args.limit:
        print(f"... {len(items) - args.limit} more")
    return 0


def discover_company_links_command(args: argparse.Namespace) -> int:
    grades = {grade.strip() for grade in args.grade.split(",") if grade.strip()}
    payload = discover_company_links(
        DiscoveryOptions(
            queue_path=Path(args.queue),
            output_path=Path(args.output),
            provider=args.provider,
            limit=args.limit,
            grades=grades,
            search=args.search,
            per_company=args.per_company,
            delay_seconds=args.delay,
        )
    )
    print(f"Discovered companies: {payload.get('count', 0)}")
    print(f"Provider: {payload.get('provider')}")
    print(f"Output: {args.output}")
    errors = payload.get("errors") or []
    if errors:
        print("Errors:")
        for error in errors[:10]:
            print(f"- {error.get('name')}: {error.get('error')}")
        if len(errors) > 10:
            print(f"... {len(errors) - 10} more")
    return 0 if not errors else 1


def print_company_link_candidates(args: argparse.Namespace) -> int:
    candidate_path = Path(args.path)
    if not candidate_path.exists():
        print(f"Candidate file not found: {candidate_path}", file=sys.stderr)
        return 1
    with candidate_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    items = list(data.get("items", []))
    print(f"Company link candidates: {len(items)}")
    for item in items[: max(args.limit, 0)]:
        print("=" * 60)
        print(f"{item.get('name')} | grade={item.get('watch_grade')} | {item.get('industry')}")
        printed = 0
        for candidate in item.get("candidates", []):
            if int(candidate.get("score", 0)) < args.min_score:
                continue
            print("-" * 40)
            print(
                f"score={candidate.get('score')} | source={candidate.get('source')} "
                f"| parser={candidate.get('parser_hint')}"
            )
            print(f"title: {candidate.get('title')}")
            print(f"url: {candidate.get('url')}")
            if candidate.get("note"):
                print(f"note: {candidate.get('note')}")
            printed += 1
            if printed >= args.per_company:
                break
    return 0


def default_platform_urls(platform: str) -> list[str]:
    if platform == "saramin":
        return DEFAULT_SARAMIN_URLS
    return DEFAULT_JOBKOREA_URLS


def check_config() -> int:
    settings = load_settings()
    openapi_missing = []
    if not settings.alio_api_url:
        openapi_missing.append("ALIO_API_URL")
    if not settings.alio_api_key:
        openapi_missing.append("ALIO_API_KEY")

    client = AlioClient(
        api_url=settings.alio_api_url,
        api_key=settings.alio_api_key,
        api_key_param=settings.alio_api_key_param,
        default_params=settings.alio_default_params,
    )

    print(f"DB: {settings.db_path}")
    print(f"ALIO_API_URL: {'set' if settings.alio_api_url else 'missing'}")
    print(f"ALIO_API_KEY: {'set' if settings.alio_api_key else 'missing'}")
    print(f"ALIO_API_KEY_PARAM: {settings.alio_api_key_param}")
    print(f"ALIO_DEFAULT_PARAMS: {json.dumps(settings.alio_default_params, ensure_ascii=False)}")
    print(f"Redacted request URL: {client.build_url(redact_key=True) or '(not available)'}")
    print(f"ALIO_PUBLIC_URL: {settings.alio_public_url or 'missing'}")
    print(
        "ALIO_PUBLIC_DEFAULT_PARAMS: "
        f"{json.dumps(settings.alio_public_default_params, ensure_ascii=False)}"
    )
    print(f"WORKNET_API_URL: {settings.worknet_api_url or 'missing'}")
    print(f"WORKNET_API_KEY: {'set' if settings.worknet_api_key else 'missing'}")
    print(f"WORKNET_ENABLED: {settings.worknet_enabled}")
    print(f"WORKNET_KEYWORDS: {', '.join(settings.worknet_keywords)}")
    print(
        "WORKNET_OCCUPATIONS: "
        f"{', '.join(settings.worknet_occupations) if settings.worknet_occupations else '(not set)'}"
    )
    print(f"COMPANY_TARGETS_PATH: {settings.company_targets_path}")

    if openapi_missing:
        print(f"OpenAPI settings missing: {', '.join(openapi_missing)}")
        if settings.alio_public_url:
            print("Public ALIO lookup is configured; fetch-alio-public can run.")
            return 0
        return 1
    print("Configuration looks ready for fetch-alio.")
    return 0


def import_sample(args: argparse.Namespace) -> int:
    settings = load_settings()
    rules = load_keywords()
    sample_path = Path(args.path)
    body = sample_path.read_bytes()
    suffix = sample_path.suffix.lower()
    if suffix == ".json":
        records = extract_records(json.loads(body.decode("utf-8-sig")))
    else:
        records = parse_response(body)
    jobs = normalize_and_score(records, rules)

    for job in jobs[: args.limit]:
        print_job(job)

    if args.dry_run:
        print(f"Sample records: {len(records)}")
        print(f"Normalized jobs: {len(jobs)}")
        print("Dry-run: DB insert skipped.")
        return 0

    with connect(settings.db_path) as conn:
        init_db(conn)
        source_id = ensure_alio_source(conn, f"sample:{sample_path.name}")
        new_count = insert_jobs(conn, jobs, source_id)
        log_crawl(conn, source_id=source_id, status="sample_import", new_jobs_count=new_count)
        mark_source_success(conn, source_id)

    print(f"Sample records: {len(records)}")
    print(f"Inserted new jobs: {new_count}")
    return 0


def print_jobs(args: argparse.Namespace) -> int:
    settings = load_settings()
    with connect(settings.db_path) as conn:
        init_db(conn)
        rows = list_jobs(conn, limit=args.limit, min_score=args.min_score)
    if not rows:
        print("No detected jobs.")
        return 0
    for row in rows:
        print_job(dict(row))
    return 0


def print_logs(args: argparse.Namespace) -> int:
    settings = load_settings()
    with connect(settings.db_path) as conn:
        init_db(conn)
        rows = list_logs(conn, limit=args.limit)
    if not rows:
        print("No crawl logs.")
        return 0
    for row in rows:
        print(
            f"{row['id']} | {row['crawled_at']} | {row['status']} | "
            f"new={row['new_jobs_count']} | duration={row['duration_ms']} | "
            f"error={row['error_message'] or ''}"
        )
    return 0


def audit_sources() -> int:
    settings = load_settings()
    print_registry_audit()
    targets = load_company_targets(settings.company_targets_path, include_disabled=True)
    enabled = [target for target in targets if target.enabled]
    disabled = [target for target in targets if not target.enabled]

    print("Company targets")
    print(f"- enabled: {len(enabled)}")
    for target in enabled:
        print(f"  [on] {target.name} | {target.parser} | {target.url}")
    print(f"- disabled / parser needed: {len(disabled)}")
    for target in disabled:
        print(f"  [off] {target.name} | {target.parser} | {target.url}")

    print("\nDB source health")
    with connect(settings.db_path) as conn:
        init_db(conn)
        rows = list_source_health(conn)
    if not rows:
        print("- no DB sources yet")
        return 0
    for row in rows:
        status = row["last_log_status"] or row["status"] or ""
        error = row["last_error_message"] or ""
        print(
            f"- {source_name(row['platform'])} | {status} | "
            f"last={row['last_crawled_at'] or '-'} | new={row['last_new_jobs_count']} | "
            f"errors={row['error_count']} | {row['url']}"
        )
        if error:
            print(f"  error: {error}")
    return 0


def print_registry_audit() -> None:
    registry_path = Path("config/company_registry.json")
    queue_path = Path("config/company_link_queue.json")
    watchlist_path = DEFAULT_WATCHLIST_PATH
    if not registry_path.exists():
        print("Company registry: not imported yet")
    else:
        with registry_path.open("r", encoding="utf-8") as file:
            registry = json.load(file)
        companies = registry.get("companies", [])
        linked = sum(1 for item in companies if item.get("link_status") == "linked")
        pending = len(companies) - linked
        print("Company registry")
        print(f"- direct-link target grades: {', '.join(registry.get('grades', []))}")
        print(f"- total: {len(companies)}")
        print(f"- linked: {linked}")
        print(f"- pending links: {pending}")
        if queue_path.exists():
            with queue_path.open("r", encoding="utf-8") as file:
                queue = json.load(file)
            print(f"- link queue: {queue.get('count', len(queue.get('items', [])))}")
    if watchlist_path.exists():
        with watchlist_path.open("r", encoding="utf-8") as file:
            watchlist = json.load(file)
        print("Company watchlist")
        print(f"- platform matching grades: {', '.join(watchlist.get('grades', []))}")
        print(f"- total: {watchlist.get('count', len(watchlist.get('companies', [])))}")
    print("")


def source_name(platform: str | None) -> str:
    labels = {
        "alio": "ALIO",
        "jobkorea": "잡코리아",
        "saramin": "사람인",
        "worknet": "워크넷",
        "company": "기업 직접",
    }
    return labels.get(str(platform or "").lower(), platform or "")


def render_dashboard_file(args: argparse.Namespace) -> int:
    settings = load_settings()
    with connect(settings.db_path) as conn:
        init_db(conn)
        summary = dashboard_summary(conn)
        jobs = list_jobs(conn, limit=args.limit or None)
        logs = list_logs(conn, limit=20)
        source_health = visible_source_health(list_source_health(conn), settings)
    write_dashboard(args.output, summary, jobs, logs, source_health)
    print(f"Wrote dashboard: {args.output}")
    return 0


def visible_source_health(rows: list[Any], settings: Any) -> list[Any]:
    disabled_company_urls = {
        target.url
        for target in load_company_targets(settings.company_targets_path, include_disabled=True)
        if not target.enabled
    }
    visible = []
    for row in rows:
        platform = str(row["platform"] or "").lower()
        if platform == "worknet" and not settings.worknet_enabled:
            continue
        if platform == "company" and row["url"] in disabled_company_urls:
            continue
        visible.append(row)
    return visible


def parse_extra_params(values: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--param must use key=value format: {value}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--param key is empty: {value}")
        params[key] = raw.strip()
    return params


def print_job(job: dict[str, Any]) -> None:
    matched_keywords = normalize_matched_keywords(job.get("matched_keywords", []))
    watch = extract_watch_info(job)
    print("-" * 60)
    if job.get("source_platform"):
        print(f"출처: {job.get('source_platform')}")
    if watch:
        print(
            "관심기업: "
            f"{watch.get('watchGrade', '')} {watch.get('name', '')} "
            f"| {watch.get('sizeGrade', '')} | {watch.get('industry', '')}"
        )
    print(f"기관: {job.get('company_name')}")
    print(f"제목: {job.get('title')}")
    print(f"마감: {job.get('deadline')}")
    print(f"경력: {job.get('career_type') or ''}")
    print(f"고용: {job.get('employment_type') or ''}")
    print(f"지역: {job.get('location') or ''}")
    print(f"분야: {job.get('field')}")
    print(f"점수: {job.get('score')}")
    print(f"매칭: {', '.join(matched_keywords)}")
    if job.get("alio_detail_url"):
        print(f"ALIO 상세: {job.get('alio_detail_url')}")
    if job.get("external_url"):
        print(f"외부 원문: {job.get('external_url')}")
    elif job.get("url"):
        print(f"링크: {job.get('url')}")


def extract_watch_info(job: dict[str, Any]) -> dict[str, str]:
    raw_data = job.get("raw_data")
    if isinstance(raw_data, str):
        parsed = parse_json_object(raw_data)
    elif isinstance(raw_data, dict):
        parsed = raw_data
    else:
        parsed = {}
    watch = parsed.get("companyWatchlist")
    if isinstance(watch, dict):
        return {str(key): str(value or "") for key, value in watch.items()}
    if job.get("watch_company_name"):
        return {
            "name": str(job.get("watch_company_name") or ""),
            "watchGrade": str(job.get("watch_grade") or ""),
            "sizeGrade": str(job.get("watch_size_grade") or ""),
            "industry": str(job.get("watch_industry") or ""),
        }
    return {}


def parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_matched_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]
    return []


def send_notifications(settings: Any, jobs: list[dict[str, Any]], threshold: int) -> None:
    for job in jobs:
        if int(job.get("score", 0)) < threshold:
            continue
        send_telegram(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            text=build_message(job),
        )
