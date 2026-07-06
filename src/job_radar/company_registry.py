from __future__ import annotations

import json
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile


SPREADSHEET_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
PACKAGE_REL_NS = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


@dataclass(frozen=True)
class RegistryCompany:
    name: str
    size_grade: str
    size_confidence: str
    include_type: str
    industry: str
    mechanical_roles: str
    products: str
    regions: str
    watch_grade: str
    verification_status: str


def read_company_xlsx(path: str | Path) -> list[RegistryCompany]:
    rows = read_xlsx_sheet(path, "전체기업")
    companies = []
    for row in rows[3:]:
        padded = [str(value or "").strip() for value in row[:10]]
        padded.extend([""] * (10 - len(padded)))
        if not padded[0]:
            continue
        companies.append(
            RegistryCompany(
                name=padded[0],
                size_grade=padded[1],
                size_confidence=padded[2],
                include_type=padded[3],
                industry=padded[4],
                mechanical_roles=padded[5],
                products=padded[6],
                regions=padded[7],
                watch_grade=padded[8],
                verification_status=padded[9],
            )
        )
    return companies


def write_registry_files(
    *,
    xlsx_path: str | Path,
    registry_output: str | Path,
    queue_output: str | Path,
    existing_targets_path: str | Path,
    grades: set[str],
    limit: int = 0,
) -> tuple[int, int]:
    companies = [
        company
        for company in read_company_xlsx(xlsx_path)
        if not grades or company.watch_grade in grades
    ]
    if limit > 0:
        companies = companies[:limit]

    existing_targets = load_existing_targets(existing_targets_path)
    registry = {
        "source": str(xlsx_path),
        "grades": sorted(grades),
        "count": len(companies),
        "companies": [
            registry_entry(company, existing_targets=existing_targets)
            for company in companies
        ],
    }
    queue = {
        "source": str(xlsx_path),
        "grades": sorted(grades),
        "count": sum(1 for company in companies if company.name not in existing_targets),
        "items": [
            queue_entry(company)
            for company in companies
            if company.name not in existing_targets
        ],
    }

    write_json(registry_output, registry)
    write_json(queue_output, queue)
    return len(registry["companies"]), len(queue["items"])


def registry_entry(
    company: RegistryCompany,
    *,
    existing_targets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    existing = existing_targets.get(company.name)
    return {
        "name": company.name,
        "size_grade": company.size_grade,
        "size_confidence": company.size_confidence,
        "include_type": company.include_type,
        "industry": company.industry,
        "mechanical_roles": company.mechanical_roles,
        "products": company.products,
        "regions": company.regions,
        "watch_grade": company.watch_grade,
        "verification_status": company.verification_status,
        "link_status": "linked" if existing else "pending",
        "target_urls": list(existing.get("urls", [])) if existing else [],
        "target_enabled": existing.get("enabled", True) if existing else False,
    }


def queue_entry(company: RegistryCompany) -> dict[str, Any]:
    query = f"{company.name} 채용"
    encoded = urllib.parse.quote(query)
    return {
        "name": company.name,
        "watch_grade": company.watch_grade,
        "size_grade": company.size_grade,
        "industry": company.industry,
        "mechanical_roles": company.mechanical_roles,
        "regions": company.regions,
        "status": "link_needed",
        "suggested_searches": {
            "naver": f"https://search.naver.com/search.naver?query={encoded}",
            "google": f"https://www.google.com/search?q={encoded}",
            "saramin": "https://www.saramin.co.kr/zf_user/search/recruit?"
            + urllib.parse.urlencode({"searchword": company.name}),
            "jobkorea": "https://www.jobkorea.co.kr/Search/?stext="
            + urllib.parse.quote(company.name),
        },
    }


def load_existing_targets(path: str | Path) -> dict[str, dict[str, Any]]:
    target_path = Path(path)
    if not target_path.exists():
        return {}
    with target_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return {
        str(item.get("name") or "").strip(): item
        for item in data.get("targets", [])
        if str(item.get("name") or "").strip()
    }


def set_company_link(
    *,
    targets_path: str | Path,
    registry_path: str | Path,
    queue_path: str | Path = "config/company_link_queue.json",
    name: str,
    url: str,
    parser: str = "",
    enabled: bool = False,
) -> None:
    targets_file = Path(targets_path)
    if targets_file.exists():
        with targets_file.open("r", encoding="utf-8") as file:
            data = json.load(file)
    else:
        data = {"targets": []}

    registry = load_registry_by_name(registry_path)
    meta = registry.get(name, {})
    targets = data.setdefault("targets", [])
    target = next((item for item in targets if item.get("name") == name), None)
    is_new_target = target is None
    if target is None:
        target = {
            "name": name,
            "group": infer_group(name),
            "sector": meta.get("industry") or "",
            "keywords": keywords_from_meta(meta),
            "urls": [],
        }
        targets.append(target)
    if enabled or is_new_target:
        target["enabled"] = enabled
    target["parser"] = parser or infer_parser(url)
    target["sector"] = target.get("sector") or meta.get("industry") or ""
    if not target.get("keywords"):
        target["keywords"] = keywords_from_meta(meta)
    urls = target.setdefault("urls", [])
    if url not in urls:
        urls.append(url)
    write_json(targets_file, data)
    target_enabled = target.get("enabled", True) is not False
    mark_registry_linked(registry_path, queue_path, name, url, target_enabled)


def mark_registry_linked(
    registry_path: str | Path,
    queue_path: str | Path,
    name: str,
    url: str,
    enabled: bool,
) -> None:
    registry_file = Path(registry_path)
    if registry_file.exists():
        with registry_file.open("r", encoding="utf-8") as file:
            registry = json.load(file)
        for item in registry.get("companies", []):
            if item.get("name") != name:
                continue
            item["link_status"] = "linked"
            item["target_enabled"] = enabled
            urls = item.setdefault("target_urls", [])
            if url not in urls:
                urls.append(url)
        write_json(registry_file, registry)

    queue_file = Path(queue_path)
    if queue_file.exists():
        with queue_file.open("r", encoding="utf-8") as file:
            queue = json.load(file)
        remaining = []
        for item in queue.get("items", []):
            if item.get("name") == name:
                continue
            remaining.append(item)
        queue["items"] = remaining
        queue["count"] = len(remaining)
        write_json(queue_file, queue)


def load_registry_by_name(path: str | Path) -> dict[str, dict[str, Any]]:
    registry_path = Path(path)
    if not registry_path.exists():
        return {}
    with registry_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return {
        str(item.get("name") or "").strip(): item
        for item in data.get("companies", [])
        if str(item.get("name") or "").strip()
    }


def infer_group(name: str) -> str:
    known_prefixes = (
        "삼성",
        "현대",
        "기아",
        "SK",
        "LG",
        "롯데",
        "한화",
        "GS",
        "HD현대",
        "LS",
        "DB",
        "DL",
        "HDC",
        "CJ",
        "효성",
        "포스코",
    )
    for prefix in known_prefixes:
        if name.startswith(prefix):
            return prefix
    return ""


def infer_parser(url: str) -> str:
    lowered = url.lower()
    if "recruiter.co.kr/app/jobnotice/list" in lowered:
        return "recruiter_mrs2"
    return "generic"


def keywords_from_meta(meta: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(meta.get(key) or "")
        for key in ("industry", "mechanical_roles", "products")
    )
    candidates = [
        "기계",
        "설비",
        "설비기술",
        "설비보전",
        "정비",
        "생산기술",
        "공정기술",
        "품질",
        "장비",
        "자동화",
        "반도체",
        "자동차",
        "방산",
        "플랜트",
        "유틸리티",
        "기술직",
        "제조",
    ]
    hits = [keyword for keyword in candidates if keyword in text]
    return hits or ["기계", "생산기술", "설비", "품질"]


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def read_xlsx_sheet(path: str | Path, sheet_name: str) -> list[list[str]]:
    with ZipFile(path) as zip_file:
        shared = read_shared_strings(zip_file)
        sheet_path = find_sheet_path(zip_file, sheet_name)
        root = ET.fromstring(zip_file.read(sheet_path))
        rows = []
        for row in root.findall("a:sheetData/a:row", SPREADSHEET_NS):
            values: list[str] = []
            for cell in row.findall("a:c", SPREADSHEET_NS):
                index = cell_column_index(cell.attrib.get("r", "A1"))
                while len(values) <= index:
                    values.append("")
                values[index] = cell_value(cell, shared)
            rows.append(values)
    return rows


def read_shared_strings(zip_file: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(".//a:t", SPREADSHEET_NS))
        for item in root.findall("a:si", SPREADSHEET_NS)
    ]


def find_sheet_path(zip_file: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("pr:Relationship", PACKAGE_REL_NS)
    }
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    for sheet in workbook.findall("a:sheets/a:sheet", SPREADSHEET_NS):
        if sheet.attrib.get("name") != sheet_name:
            continue
        target = rel_targets[sheet.attrib[rel_ns]]
        if target.startswith("/"):
            return target.lstrip("/")
        if target.startswith("xl/"):
            return target
        if target.startswith("worksheets/"):
            return "xl/" + target
        return "xl/worksheets/" + target.split("/")[-1]
    raise ValueError(f"Sheet not found: {sheet_name}")


def cell_column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + ord(char.upper()) - 64
    return index - 1


def cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", SPREADSHEET_NS))
    value = cell.find("a:v", SPREADSHEET_NS)
    if value is None:
        return ""
    raw = value.text or ""
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    return raw
