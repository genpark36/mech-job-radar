from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


FIELD_ALIASES = {
    "source_record_id": (
        "recrutPblntSn",
        "sn",
        "recrutSn",
        "recruitmentSn",
        "pbancSn",
    ),
    "company_name": (
        "기관명",
        "공시기관",
        "기관",
        "instNm",
        "orgNm",
        "pbancInstNm",
        "recrutInstNm",
        "instnNm",
        "orgnztNm",
    ),
    "title": (
        "제목",
        "채용제목",
        "공고명",
        "recrutPbancTtl",
        "pbancTtl",
        "title",
        "recrutPbancTitle",
        "pbancTitle",
    ),
    "posted_date": (
        "시작일",
        "공고시작일",
        "채용시작일",
        "pbancBgngYmd",
        "recrutPbancBgngYmd",
        "startDate",
        "bgngYmd",
        "beginDate",
    ),
    "deadline": (
        "종료일",
        "마감일",
        "공고마감일",
        "채용마감일",
        "pbancEndYmd",
        "recrutPbancEndYmd",
        "deadline",
        "endYmd",
        "endDate",
    ),
    "field": ("채용분야", "분야", "ncsCdNmLst", "ncsCdNm", "recrutSeNm", "field"),
    "employment_type": ("고용형태", "hireTypeNm", "hireTypeNmLst", "employType", "employmentType"),
    "career_type": ("채용구분", "경력구분", "recrutTypeNm", "careerType", "careerSeNm"),
    "location": ("근무지", "근무지역", "workRgnNmLst", "workRgnNm", "location"),
    "external_url": ("URL", "상세URL", "공고URL", "srcUrl", "detailUrl", "url", "recrutPbancUrl"),
}

ALIO_RECRUIT_DETAIL_BASE_URL = "https://opendata.alio.go.kr/new/odaApiMng/recrutInquiryDetail.do"

ALIO_CODE_LABELS = {
    "R1010": "정규직",
    "R1020": "계약직",
    "R1030": "무기계약직",
    "R1040": "비정규직",
    "R1050": "청년인턴",
    "R1060": "청년인턴(체험형)",
    "R1070": "청년인턴(채용형)",
    "R2010": "신입",
    "R2020": "경력",
    "R2030": "신입+경력",
    "R2040": "외국인 전형",
    "R3010": "서울",
    "R3011": "인천",
    "R3012": "대전",
    "R3013": "대구",
    "R3014": "부산",
    "R3015": "광주",
    "R3016": "울산",
    "R3017": "경기",
    "R3018": "강원",
    "R3019": "충남",
    "R3020": "충북",
    "R3021": "경북",
    "R3022": "경남",
    "R3023": "전남",
    "R3024": "전북",
    "R3025": "제주",
    "R3026": "세종",
    "R3030": "해외",
    "R600014": "건설",
    "R600015": "기계",
    "R600016": "재료",
    "R600017": "화학",
    "R600019": "전기.전자",
    "R600020": "정보통신",
    "R600023": "환경.에너지.안전",
    "R600025": "연구",
    "R7010": "학력무관",
    "R7020": "중졸이하",
    "R7030": "고졸",
    "R7040": "대졸(2~3년)",
    "R7050": "대졸(4년)",
    "R7060": "석사",
    "R7070": "박사",
}


@dataclass(frozen=True)
class FetchResult:
    records: list[dict[str, Any]]
    duration_ms: int
    content_type: str
    request_url: str


class AlioClient:
    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        api_key_param: str,
        default_params: dict[str, str],
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.api_key_param = api_key_param
        self.default_params = default_params

    def fetch(self, extra_params: dict[str, str] | None = None) -> FetchResult:
        if not self.api_url:
            raise ValueError("ALIO_API_URL is not configured")
        if not self.api_key:
            raise ValueError("ALIO_API_KEY is not configured")

        params = dict(self.default_params)
        params[self.api_key_param] = self.api_key
        if extra_params:
            params.update(extra_params)

        url = self.build_url(params=params, redact_key=False)
        start = time.perf_counter()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "JobRadar-Personal/0.1 (private use)"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
        duration_ms = int((time.perf_counter() - start) * 1000)
        records = parse_response(body, content_type)
        return FetchResult(
            records=records,
            duration_ms=duration_ms,
            content_type=content_type,
            request_url=self.build_url(params=params, redact_key=True),
        )

    def build_url(
        self,
        *,
        params: dict[str, str] | None = None,
        extra_params: dict[str, str] | None = None,
        redact_key: bool = True,
    ) -> str:
        if not self.api_url:
            return ""
        merged = dict(self.default_params)
        if self.api_key:
            merged[self.api_key_param] = "***" if redact_key else self.api_key
        if params:
            merged.update(params)
            if redact_key and self.api_key_param in merged:
                merged[self.api_key_param] = "***"
        if extra_params:
            merged.update(extra_params)
        delimiter = "&" if "?" in self.api_url else "?"
        return f"{self.api_url}{delimiter}{urllib.parse.urlencode(merged)}"


class AlioPublicClient:
    def __init__(self, *, url: str, default_params: dict[str, str]) -> None:
        self.url = url
        self.default_params = default_params

    def fetch(self, extra_params: dict[str, str] | None = None) -> FetchResult:
        if not self.url:
            raise ValueError("ALIO_PUBLIC_URL is not configured")
        params = dict(self.default_params)
        if extra_params:
            params.update(extra_params)
        payload = urllib.parse.urlencode(params).encode("utf-8")
        start = time.perf_counter()
        request = urllib.request.Request(
            self.url,
            data=payload,
            method="POST",
            headers={
                "User-Agent": "JobRadar-Personal/0.1 (private use)",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
        duration_ms = int((time.perf_counter() - start) * 1000)
        records = parse_response(body, content_type)
        return FetchResult(
            records=records,
            duration_ms=duration_ms,
            content_type=content_type,
            request_url=f"{self.url} POST {urllib.parse.urlencode(params)}",
        )


def parse_response(body: bytes, content_type: str = "") -> list[dict[str, Any]]:
    text = body.decode("utf-8-sig", errors="replace")
    if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
        parsed = json.loads(text)
        return extract_records(parsed)
    return extract_records(xml_to_dict(ET.fromstring(text)))


def extract_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        dict_items = [item for item in value if isinstance(item, dict)]
        if dict_items:
            return dict_items
        return []
    if not isinstance(value, dict):
        return []

    preferred_keys = (
        "items",
        "item",
        "data",
        "list",
        "result",
        "body",
        "response",
        "rows",
    )
    for key in preferred_keys:
        if key in value:
            records = extract_records(value[key])
            if records:
                return records

    for child in value.values():
        records = extract_records(child)
        if records:
            return records
    return []


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        field: first_value(record, aliases)
        for field, aliases in FIELD_ALIASES.items()
    }
    for field in ("field", "employment_type", "career_type", "location"):
        normalized[field] = expand_code_labels(normalized[field])
    normalized["posted_date"] = normalize_date(normalized["posted_date"])
    normalized["deadline"] = normalize_date(normalized["deadline"])
    normalized["company_name"] = normalized["company_name"] or "미확인 기관"
    normalized["title"] = normalized["title"] or "제목 미확인 공고"
    normalized["source_platform"] = "alio"
    normalized["alio_detail_url"] = build_alio_detail_url(normalized["source_record_id"])
    normalized["url"] = normalized["alio_detail_url"] or normalized["external_url"]
    normalized["unique_key"] = unique_key(normalized)
    normalized["raw_data"] = record
    return normalized


def first_value(record: dict[str, Any], aliases: tuple[str, ...]) -> str:
    lowered = {str(key).lower(): value for key, value in record.items()}
    for alias in aliases:
        if alias in record and record[alias] not in (None, ""):
            return clean_text(record[alias])
        value = lowered.get(alias.lower())
        if value not in (None, ""):
            return clean_text(value)
    return ""


def clean_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(clean_text(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return " ".join(str(value).split())


def expand_code_labels(value: str) -> str:
    if not value:
        return ""
    tokens = value.replace(";", ",").replace("|", ",").split(",")
    expanded = []
    changed = False
    for raw_token in tokens:
        token = raw_token.strip()
        label = ALIO_CODE_LABELS.get(token)
        if label:
            expanded.append(f"{token} {label}")
            changed = True
        elif token:
            expanded.append(token)
    return ", ".join(expanded) if changed else value


def normalize_date(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return value


def build_alio_detail_url(source_record_id: str) -> str:
    record_id = "".join(ch for ch in str(source_record_id or "") if ch.isdigit())
    if not record_id:
        return ""
    return f"{ALIO_RECRUIT_DETAIL_BASE_URL}?sn={record_id}"


def unique_key(job: dict[str, Any]) -> str:
    source_record_id = str(job.get("source_record_id", "") or "").strip()
    if source_record_id:
        platform = str(job.get("source_platform", "") or "alio").strip()
        return hashlib.sha256(f"{platform}|{source_record_id}".encode("utf-8")).hexdigest()
    base = "|".join(
        [
            job.get("company_name", ""),
            job.get("title", ""),
            job.get("deadline", ""),
            job.get("url", ""),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def xml_to_dict(element: ET.Element) -> dict[str, Any]:
    children = list(element)
    if not children:
        return {strip_namespace(element.tag): element.text or ""}

    grouped: dict[str, Any] = {}
    for child in children:
        key = strip_namespace(child.tag)
        value = xml_to_dict(child)[key]
        if key in grouped:
            if not isinstance(grouped[key], list):
                grouped[key] = [grouped[key]]
            grouped[key].append(value)
        else:
            grouped[key] = value
    return {strip_namespace(element.tag): grouped}


def strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
