from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import load_dotenv


@dataclass(frozen=True)
class Settings:
    alio_api_url: str
    alio_api_key: str
    alio_api_key_param: str
    alio_default_params: dict[str, str]
    alio_public_url: str
    alio_public_default_params: dict[str, str]
    alio_public_enabled: bool
    worknet_api_url: str
    worknet_api_key: str
    worknet_enabled: bool
    worknet_keywords: list[str]
    worknet_occupations: list[str]
    company_targets_path: Path
    db_path: Path
    telegram_bot_token: str
    telegram_chat_id: str


def load_settings() -> Settings:
    load_dotenv()

    raw_params = os.getenv(
        "ALIO_DEFAULT_PARAMS",
        '{"pageNo":"1","numOfRows":"100","type":"json"}',
    )
    try:
        params: dict[str, Any] = json.loads(raw_params)
    except json.JSONDecodeError as exc:
        raise ValueError("ALIO_DEFAULT_PARAMS must be valid JSON") from exc
    raw_public_params = os.getenv(
        "ALIO_PUBLIC_DEFAULT_PARAMS",
        (
            '{"pageNo":"1","numOfRows":"100",'
            '"ncsCdLst":"R600014,R600015,R600016,R600017,R600019,R600023,R600025",'
            '"ongoingYn":"Y"}'
        ),
    )
    try:
        public_params: dict[str, Any] = json.loads(raw_public_params)
    except json.JSONDecodeError as exc:
        raise ValueError("ALIO_PUBLIC_DEFAULT_PARAMS must be valid JSON") from exc
    raw_worknet_keywords = os.getenv(
        "WORKNET_KEYWORDS",
        (
            "기계,기계직,기계설비,설비,설비보전,보전,정비,유지보수,공무,"
            "생산기술,공정기술,설비기술,제조기술,품질,품질관리,플랜트,"
            "자동차,모빌리티,반도체,방산,철도차량,발전설비,유틸리티,공조,"
            "냉동,보일러,에너지,안전관리"
        ),
    )
    raw_worknet_occupations = os.getenv("WORKNET_OCCUPATIONS", "")

    return Settings(
        alio_api_url=os.getenv("ALIO_API_URL", "").strip(),
        alio_api_key=os.getenv("ALIO_API_KEY", "").strip(),
        alio_api_key_param=os.getenv("ALIO_API_KEY_PARAM", "serviceKey").strip(),
        alio_default_params={str(k): str(v) for k, v in params.items()},
        alio_public_url=os.getenv(
            "ALIO_PUBLIC_URL",
            "https://opendata.alio.go.kr/new/odaApiMng/recrutInquiryAjaxList.do",
        ).strip(),
        alio_public_default_params={str(k): str(v) for k, v in public_params.items()},
        alio_public_enabled=os.getenv("ALIO_PUBLIC_ENABLED", "1").strip().lower()
        in {"1", "true", "yes", "y"},
        worknet_api_url=os.getenv(
            "WORKNET_API_URL",
            "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do",
        ).strip(),
        worknet_api_key=os.getenv("WORKNET_API_KEY", "").strip(),
        worknet_enabled=os.getenv("WORKNET_ENABLED", "0").strip().lower()
        in {"1", "true", "yes", "y"},
        worknet_keywords=[item.strip() for item in raw_worknet_keywords.split(",") if item.strip()],
        worknet_occupations=[
            item.strip() for item in raw_worknet_occupations.replace("|", ",").split(",") if item.strip()
        ],
        company_targets_path=Path(os.getenv("COMPANY_TARGETS_PATH", "config/company_targets.json")),
        db_path=Path(os.getenv("MECH_JOB_RADAR_DB", "data/job_radar.sqlite3")),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def load_keywords(path: str | Path = "config/keywords.json") -> dict[str, list[dict[str, Any]]]:
    keyword_path = Path(path)
    with keyword_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return {
        "positive": list(data.get("positive", [])),
        "negative": list(data.get("negative", [])),
        "bonus": list(data.get("bonus", [])),
    }
