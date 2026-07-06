from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
USER_AGENT = "PersonalJobMonitor/0.1 (+private low-frequency job alert use)"


@dataclass(frozen=True)
class DiscoveryOptions:
    queue_path: Path
    output_path: Path
    provider: str = "auto"
    limit: int = 20
    grades: set[str] | None = None
    search: str = ""
    per_company: int = 8
    delay_seconds: float = 1.0


def discover_company_links(options: DiscoveryOptions) -> dict[str, Any]:
    items = select_queue_items(
        load_queue_items(options.queue_path),
        limit=options.limit,
        grades=options.grades or set(),
        search=options.search,
    )
    brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    use_brave = options.provider in {"auto", "brave"} and bool(brave_key)
    results = []
    errors = []
    for index, item in enumerate(items):
        if index and use_brave and options.delay_seconds > 0:
            time.sleep(options.delay_seconds)
        candidates = generated_candidates(item)
        if use_brave:
            try:
                candidates.extend(
                    brave_candidates(
                        item,
                        api_key=brave_key,
                        count=options.per_company,
                    )
                )
            except Exception as exc:
                errors.append({"name": item.get("name"), "error": str(exc)})
        elif options.provider == "brave":
            errors.append(
                {
                    "name": item.get("name"),
                    "error": "BRAVE_SEARCH_API_KEY is not set.",
                }
            )
        ranked = dedupe_candidates(candidates)
        results.append(
            {
                "name": item.get("name"),
                "watch_grade": item.get("watch_grade"),
                "size_grade": item.get("size_grade"),
                "industry": item.get("industry"),
                "mechanical_roles": item.get("mechanical_roles"),
                "candidate_count": len(ranked),
                "candidates": ranked,
            }
        )

    payload = {
        "provider": "brave" if use_brave else "generated",
        "source_queue": str(options.queue_path),
        "count": len(results),
        "items": results,
        "errors": errors,
    }
    write_json(options.output_path, payload)
    return payload


def load_queue_items(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as file:
        data = json.load(file)
    return list(data.get("items", []))


def select_queue_items(
    items: list[dict[str, Any]],
    *,
    limit: int,
    grades: set[str],
    search: str,
) -> list[dict[str, Any]]:
    selected = list(items)
    if grades:
        selected = [item for item in selected if str(item.get("watch_grade") or "") in grades]
    needle = search.strip().lower()
    if needle:
        selected = [
            item
            for item in selected
            if needle
            in " ".join(
                str(item.get(key) or "")
                for key in ("name", "industry", "mechanical_roles", "regions")
            ).lower()
        ]
    return selected[:limit] if limit > 0 else selected


def generated_candidates(item: dict[str, Any]) -> list[dict[str, Any]]:
    searches = item.get("suggested_searches") or {}
    name = str(item.get("name") or "")
    candidates = []
    if searches.get("saramin"):
        candidates.append(
            candidate(
                url=searches["saramin"],
                title=f"{name} 사람인 검색",
                source="generated_platform_search",
                score=24,
                note="사람인 회사명 검색 URL. 공고 파싱 가능 여부는 별도 검증 필요.",
            )
        )
    if searches.get("jobkorea"):
        candidates.append(
            candidate(
                url=searches["jobkorea"],
                title=f"{name} 잡코리아 검색",
                source="generated_platform_search",
                score=12,
                note="잡코리아 검색 URL. 현재 robots 정책상 자동 크롤링 대상에서는 제외될 수 있음.",
            )
        )
    if searches.get("naver"):
        candidates.append(
            candidate(
                url=searches["naver"],
                title=f"{name} 네이버 검색",
                source="manual_search",
                score=8,
                note="공식 채용페이지를 사람이 확인하기 위한 검색 주소.",
            )
        )
    if searches.get("google"):
        candidates.append(
            candidate(
                url=searches["google"],
                title=f"{name} Google 검색",
                source="manual_search",
                score=8,
                note="공식 채용페이지를 사람이 확인하기 위한 검색 주소.",
            )
        )
    return candidates


def brave_candidates(
    item: dict[str, Any],
    *,
    api_key: str,
    count: int,
) -> list[dict[str, Any]]:
    name = str(item.get("name") or "")
    query = f"{name} 채용 공식"
    params = urllib.parse.urlencode(
        {
            "q": query,
            "count": str(max(1, min(count, 20))),
            "country": "KR",
            "search_lang": "ko",
            "safesearch": "moderate",
        }
    )
    request = urllib.request.Request(
        f"{BRAVE_SEARCH_URL}?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    results = []
    for result in payload.get("web", {}).get("results", []):
        url = str(result.get("url") or "")
        title = clean_text(str(result.get("title") or ""))
        description = clean_text(str(result.get("description") or ""))
        if not url or is_search_or_noise_url(url):
            continue
        results.append(
            candidate(
                url=url,
                title=title,
                source="brave_search",
                score=score_candidate(url, title, description, name),
                note=description[:240],
            )
        )
    return results


def candidate(
    *,
    url: str,
    title: str,
    source: str,
    score: int,
    note: str,
) -> dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "source": source,
        "score": score,
        "parser_hint": parser_hint(url),
        "note": note,
    }


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for item in candidates:
        url = normalize_url(str(item.get("url") or ""))
        if not url:
            continue
        existing = by_url.get(url)
        current = dict(item)
        current["url"] = url
        if existing is None or int(current.get("score", 0)) > int(existing.get("score", 0)):
            by_url[url] = current
    return sorted(by_url.values(), key=lambda item: int(item.get("score", 0)), reverse=True)


def score_candidate(url: str, title: str, description: str, company_name: str) -> int:
    text = f"{url} {title} {description}".lower()
    score = 0
    if company_name and company_name.lower() in text:
        score += 12
    if any(token in text for token in ("채용", "인재", "입사지원", "career", "careers", "recruit", "jobs")):
        score += 30
    if any(token in url.lower() for token in ("career", "careers", "recruit", "jobs", "jobnotice")):
        score += 24
    if "recruiter.co.kr" in url.lower():
        score += 16
    if any(token in url.lower() for token in ("saramin.co.kr", "jobkorea.co.kr")):
        score += 6
    if is_search_or_noise_url(url):
        score -= 40
    return score


def parser_hint(url: str) -> str:
    lowered = url.lower()
    if "recruiter.co.kr/app/jobnotice/list" in lowered:
        return "recruiter_mrs2"
    if "saramin.co.kr" in lowered:
        return "platform_saramin"
    if "jobkorea.co.kr" in lowered:
        return "platform_jobkorea"
    return "generic"


def is_search_or_noise_url(url: str) -> bool:
    lowered = url.lower()
    blocked_hosts = (
        "google.com/search",
        "search.naver.com",
        "duckduckgo.com",
        "bing.com/search",
        "youtube.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
    )
    return any(host in lowered for host in blocked_hosts)


def normalize_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    parsed = parsed._replace(fragment="")
    return urllib.parse.urlunparse(parsed)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
