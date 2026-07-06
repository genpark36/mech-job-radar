from __future__ import annotations

from typing import Any


def score_job(job: dict[str, Any], rules: dict[str, list[dict[str, Any]]]) -> tuple[int, list[str]]:
    searchable = " ".join(
        str(job.get(key, ""))
        for key in (
            "title",
            "company_name",
            "field",
            "employment_type",
            "career_type",
            "location",
        )
    ).lower()

    score = 0
    matched: list[str] = []
    for category in ("positive", "negative", "bonus"):
        for rule in rules.get(category, []):
            keyword = str(rule.get("keyword", "")).strip()
            if not keyword:
                continue
            if keyword.lower() in searchable:
                weight = int(rule.get("weight", 0))
                score += weight
                matched.append(f"{keyword}({weight:+d})")
    return score, matched

