from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .company_registry import RegistryCompany, read_company_xlsx


DEFAULT_WATCHLIST_PATH = Path("config/company_watchlist.json")


@dataclass(frozen=True)
class WatchCompany:
    name: str
    normalized_name: str
    watch_grade: str
    size_grade: str
    industry: str
    mechanical_roles: str
    regions: str


class CompanyWatchlist:
    def __init__(self, companies: list[WatchCompany]) -> None:
        self.companies = companies
        self.by_exact = {company.normalized_name: company for company in companies}
        self.by_length = sorted(
            companies,
            key=lambda company: len(company.normalized_name),
            reverse=True,
        )

    def match(self, company_name: str) -> WatchCompany | None:
        normalized = normalize_company_name(company_name)
        if not normalized:
            return None
        exact = self.by_exact.get(normalized)
        if exact:
            return exact
        if len(normalized) < 4:
            return None
        for company in self.by_length:
            target = company.normalized_name
            if len(target) < 4:
                continue
            if target in normalized or normalized in target:
                return company
        return None


def write_company_watchlist(
    *,
    xlsx_path: str | Path,
    output_path: str | Path = DEFAULT_WATCHLIST_PATH,
    grades: set[str] | None = None,
    limit: int = 0,
) -> int:
    selected = [
        company
        for company in read_company_xlsx(xlsx_path)
        if not grades or company.watch_grade in grades
    ]
    if limit > 0:
        selected = selected[:limit]
    payload = {
        "source": str(xlsx_path),
        "grades": sorted(grades or []),
        "count": len(selected),
        "companies": [watchlist_entry(company) for company in selected],
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return len(selected)


def load_company_watchlist(path: str | Path = DEFAULT_WATCHLIST_PATH) -> CompanyWatchlist:
    watchlist_path = Path(path)
    if not watchlist_path.exists():
        return CompanyWatchlist([])
    with watchlist_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    companies = []
    for item in data.get("companies", []):
        name = str(item.get("name") or "").strip()
        normalized = str(item.get("normalized_name") or "").strip()
        if not name or not normalized:
            continue
        companies.append(
            WatchCompany(
                name=name,
                normalized_name=normalized,
                watch_grade=str(item.get("watch_grade") or ""),
                size_grade=str(item.get("size_grade") or ""),
                industry=str(item.get("industry") or ""),
                mechanical_roles=str(item.get("mechanical_roles") or ""),
                regions=str(item.get("regions") or ""),
            )
        )
    return CompanyWatchlist(companies)


def tag_watchlist_jobs(
    jobs: list[dict[str, Any]],
    watchlist: CompanyWatchlist | None = None,
) -> list[dict[str, Any]]:
    active_watchlist = watchlist or load_company_watchlist()
    if not active_watchlist.companies:
        return jobs
    for job in jobs:
        match = active_watchlist.match(str(job.get("company_name") or ""))
        if not match:
            continue
        raw_data = job.get("raw_data")
        if not isinstance(raw_data, dict):
            raw_data = {}
        raw_data["companyWatchlist"] = {
            "name": match.name,
            "watchGrade": match.watch_grade,
            "sizeGrade": match.size_grade,
            "industry": match.industry,
            "mechanicalRoles": match.mechanical_roles,
            "regions": match.regions,
        }
        job["raw_data"] = raw_data
        job["watch_company_name"] = match.name
        job["watch_grade"] = match.watch_grade
        job["watch_size_grade"] = match.size_grade
        job["watch_industry"] = match.industry
        matched = job.get("matched_keywords")
        if isinstance(matched, list):
            marker = f"관심기업{match.watch_grade}(+0)"
            if marker not in matched:
                matched.append(marker)
    return jobs


def watchlist_entry(company: RegistryCompany) -> dict[str, Any]:
    return {
        "name": company.name,
        "normalized_name": normalize_company_name(company.name),
        "watch_grade": company.watch_grade,
        "size_grade": company.size_grade,
        "industry": company.industry,
        "mechanical_roles": company.mechanical_roles,
        "regions": company.regions,
    }


def normalize_company_name(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    replacements = (
        "주식회사",
        "(주)",
        "㈜",
        "유한회사",
        "재단법인",
        "사단법인",
        "농업회사법인",
        "어업회사법인",
        "의료법인",
        "학교법인",
    )
    for token in replacements:
        text = text.replace(token, "")
    text = re.sub(r"[^0-9a-z가-힣]+", "", text)
    return text
