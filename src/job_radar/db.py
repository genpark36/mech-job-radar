from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any


ALIO_RECRUIT_DETAIL_BASE_URL = "https://opendata.alio.go.kr/new/odaApiMng/recrutInquiryDetail.do"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT DEFAULT 'public',
    industry TEXT DEFAULT 'public_inst',
    priority INTEGER DEFAULT 1,
    homepage_url TEXT,
    is_active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    memo TEXT
);

CREATE TABLE IF NOT EXISTS watch_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    url TEXT NOT NULL,
    source_type TEXT DEFAULT 'api',
    platform TEXT DEFAULT 'alio',
    crawl_frequency_min INTEGER DEFAULT 180,
    selector_config TEXT,
    last_crawled_at DATETIME,
    status TEXT DEFAULT 'active',
    error_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS detected_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    source_id INTEGER REFERENCES watch_sources(id),
    company_name TEXT,
    title TEXT NOT NULL,
    url TEXT,
    source_platform TEXT,
    source_record_id TEXT,
    alio_detail_url TEXT,
    external_url TEXT,
    unique_key TEXT UNIQUE,
    posted_date TEXT,
    deadline TEXT,
    field TEXT,
    employment_type TEXT,
    career_type TEXT,
    location TEXT,
    score INTEGER DEFAULT 0,
    matched_keywords TEXT,
    is_notified INTEGER DEFAULT 0,
    is_expired INTEGER DEFAULT 0,
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    raw_data TEXT
);

CREATE TABLE IF NOT EXISTS crawl_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES watch_sources(id),
    crawled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    new_jobs_count INTEGER DEFAULT 0,
    error_message TEXT,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS keyword_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    category TEXT,
    weight INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    memo TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES detected_jobs(id),
    channel TEXT,
    sent_at DATETIME,
    status TEXT,
    message_preview TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate_schema(conn)
    backfill_job_links(conn)
    conn.commit()


def migrate_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(detected_jobs)").fetchall()
    }
    migrations = {
        "source_record_id": "ALTER TABLE detected_jobs ADD COLUMN source_record_id TEXT",
        "source_platform": "ALTER TABLE detected_jobs ADD COLUMN source_platform TEXT",
        "alio_detail_url": "ALTER TABLE detected_jobs ADD COLUMN alio_detail_url TEXT",
        "external_url": "ALTER TABLE detected_jobs ADD COLUMN external_url TEXT",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)


def backfill_job_links(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, company_name, title, deadline, url, source_platform, source_record_id,
               alio_detail_url, external_url, raw_data
        FROM detected_jobs
        WHERE source_record_id IS NULL
           OR source_record_id = ''
           OR source_platform IS NULL
           OR source_platform = ''
           OR alio_detail_url IS NULL
           OR alio_detail_url = ''
           OR (
                source_platform != 'alio'
                AND alio_detail_url LIKE 'https://opendata.alio.go.kr/%'
           )
           OR external_url IS NULL
           OR external_url = ''
        """
    ).fetchall()
    for row in rows:
        raw_data = parse_raw_data(row["raw_data"])
        source_record_id = str(
            row["source_record_id"]
            or first_raw_value(raw_data, ("recrutPblntSn", "sn", "recrutSn", "pbancSn"))
            or ""
        ).strip()
        source_platform = row["source_platform"] or first_raw_value(raw_data, ("sourcePlatform",))
        source_platform = source_platform or ("alio" if source_record_id or row["alio_detail_url"] else "")
        alio_detail_url = row["alio_detail_url"] or ""
        if source_platform == "alio":
            alio_detail_url = alio_detail_url or build_alio_detail_url(source_record_id)
        elif alio_detail_url.startswith("https://opendata.alio.go.kr/"):
            alio_detail_url = ""
        external_url = row["external_url"] or first_raw_value(
            raw_data,
            ("srcUrl", "detailUrl", "recrutPbancUrl", "url", "URL", "상세URL", "공고URL"),
        )
        primary_url = alio_detail_url or row["url"] or external_url
        unique_key = build_unique_key(
            source_platform=source_platform,
            source_record_id=source_record_id,
            company_name=row["company_name"],
            title=row["title"],
            deadline=row["deadline"],
            url=primary_url,
        )
        conn.execute(
            """
            UPDATE detected_jobs
            SET source_record_id = ?,
                source_platform = ?,
                alio_detail_url = ?,
                external_url = ?,
                url = ?,
                unique_key = ?
            WHERE id = ?
            """,
            (
                source_record_id,
                source_platform,
                alio_detail_url,
                external_url,
                primary_url,
                unique_key,
                row["id"],
            ),
        )


def seed_keywords(conn: sqlite3.Connection, groups: dict[str, list[dict[str, Any]]]) -> int:
    count = 0
    for category, rules in groups.items():
        for rule in rules:
            cur = conn.execute(
                """
                INSERT INTO keyword_rules(keyword, category, weight, memo)
                SELECT ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM keyword_rules
                    WHERE keyword = ? AND category = ?
                )
                """,
                (
                    rule["keyword"],
                    category,
                    int(rule.get("weight", 0)),
                    rule.get("memo", ""),
                    rule["keyword"],
                    category,
                ),
            )
            count += cur.rowcount
    conn.commit()
    return count


def ensure_company(conn: sqlite3.Connection, name: str) -> int:
    normalized = name.strip() or "미확인 기관"
    conn.execute(
        "INSERT OR IGNORE INTO companies(name, type, industry, priority) VALUES (?, 'public', 'public_inst', 1)",
        (normalized,),
    )
    row = conn.execute("SELECT id FROM companies WHERE name = ?", (normalized,)).fetchone()
    conn.commit()
    return int(row["id"])


def ensure_alio_source(conn: sqlite3.Connection, url: str) -> int:
    return ensure_source(conn, url=url, platform="alio", source_type="api")


def ensure_source(
    conn: sqlite3.Connection,
    *,
    url: str,
    platform: str,
    source_type: str = "platform",
) -> int:
    conn.execute(
        """
        INSERT OR IGNORE INTO watch_sources(url, source_type, platform)
        VALUES (?, ?, ?)
        """,
        (url, source_type, platform),
    )
    row = conn.execute(
        "SELECT id FROM watch_sources WHERE url = ? AND platform = ?",
        (url, platform),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def insert_jobs(conn: sqlite3.Connection, jobs: Iterable[dict[str, Any]], source_id: int) -> int:
    new_count = 0
    for job in jobs:
        company_id = ensure_company(conn, job["company_name"])
        source_platform = str(job.get("source_platform", "") or "alio").strip()
        source_record_id = str(job.get("source_record_id", "") or "").strip()
        if source_record_id:
            existing = conn.execute(
                """
                SELECT id FROM detected_jobs
                WHERE source_platform = ? AND source_record_id = ?
                """,
                (source_platform, source_record_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE detected_jobs
                    SET company_id = ?,
                        source_id = ?,
                        company_name = ?,
                        title = ?,
                        url = ?,
                        source_platform = ?,
                        alio_detail_url = ?,
                        external_url = ?,
                        unique_key = ?,
                        posted_date = ?,
                        deadline = ?,
                        field = ?,
                        employment_type = ?,
                        career_type = ?,
                        location = ?,
                        score = ?,
                        matched_keywords = ?,
                        raw_data = ?
                    WHERE id = ?
                    """,
                    (
                        company_id,
                        source_id,
                        job["company_name"],
                        job["title"],
                        job.get("url", ""),
                        source_platform,
                        job.get("alio_detail_url", ""),
                        job.get("external_url", ""),
                        job["unique_key"],
                        job.get("posted_date", ""),
                        job.get("deadline", ""),
                        job.get("field", ""),
                        job.get("employment_type", ""),
                        job.get("career_type", ""),
                        job.get("location", ""),
                        int(job.get("score", 0)),
                        json.dumps(job.get("matched_keywords", []), ensure_ascii=False),
                        json.dumps(job.get("raw_data", {}), ensure_ascii=False),
                        existing["id"],
                    ),
                )
                continue
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO detected_jobs(
                company_id, source_id, company_name, title, url,
                source_platform, source_record_id, alio_detail_url, external_url, unique_key,
                posted_date, deadline, field, employment_type, career_type,
                location, score, matched_keywords, raw_data
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                source_id,
                job["company_name"],
                job["title"],
                job.get("url", ""),
                source_platform,
                source_record_id,
                job.get("alio_detail_url", ""),
                job.get("external_url", ""),
                job["unique_key"],
                job.get("posted_date", ""),
                job.get("deadline", ""),
                job.get("field", ""),
                job.get("employment_type", ""),
                job.get("career_type", ""),
                job.get("location", ""),
                int(job.get("score", 0)),
                json.dumps(job.get("matched_keywords", []), ensure_ascii=False),
                json.dumps(job.get("raw_data", {}), ensure_ascii=False),
            ),
        )
        new_count += cur.rowcount
    conn.commit()
    return new_count


def log_crawl(
    conn: sqlite3.Connection,
    *,
    source_id: int | None,
    status: str,
    new_jobs_count: int = 0,
    error_message: str = "",
    duration_ms: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_logs(source_id, status, new_jobs_count, error_message, duration_ms)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_id, status, new_jobs_count, error_message, duration_ms),
    )
    conn.commit()


def mark_source_success(conn: sqlite3.Connection, source_id: int | None) -> None:
    if source_id is None:
        return
    conn.execute(
        """
        UPDATE watch_sources
        SET last_crawled_at = CURRENT_TIMESTAMP,
            status = 'active',
            error_count = 0
        WHERE id = ?
        """,
        (source_id,),
    )
    conn.commit()


def mark_source_failure(conn: sqlite3.Connection, source_id: int | None) -> None:
    if source_id is None:
        return
    conn.execute(
        """
        UPDATE watch_sources
        SET last_crawled_at = CURRENT_TIMESTAMP,
            status = 'error',
            error_count = error_count + 1
        WHERE id = ?
        """,
        (source_id,),
    )
    conn.commit()


def list_jobs(
    conn: sqlite3.Connection,
    limit: int | None = 20,
    min_score: int | None = None,
) -> list[sqlite3.Row]:
    sql = """
        SELECT id, company_name, title, deadline, field, employment_type,
               career_type, location, score, matched_keywords, url,
               source_platform, source_record_id, alio_detail_url, external_url,
               detected_at, raw_data
        FROM detected_jobs
    """
    params: list[Any] = []
    if min_score is not None:
        sql += " WHERE score >= ?"
        params.append(min_score)
    sql += " ORDER BY detected_at DESC, score DESC"
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params).fetchall())


def list_logs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, crawled_at, status, new_jobs_count, error_message, duration_ms
            FROM crawl_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    )


def list_source_health(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            WITH grouped_sources AS (
                SELECT platform,
                       source_type,
                       url,
                       MAX(id) AS id,
                       MAX(last_crawled_at) AS last_crawled_at,
                       SUM(error_count) AS error_count,
                       CASE
                           WHEN SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) > 0
                           THEN 'error'
                           ELSE MAX(status)
                       END AS status
                FROM watch_sources
                GROUP BY platform, source_type, url
            )
            SELECT gs.id,
                   gs.platform,
                   gs.source_type,
                   gs.url,
                   gs.status,
                   gs.error_count,
                   gs.last_crawled_at,
                   (
                       SELECT cl.status
                       FROM crawl_logs cl
                       JOIN watch_sources ws ON ws.id = cl.source_id
                       WHERE ws.platform = gs.platform
                         AND ws.source_type = gs.source_type
                         AND ws.url = gs.url
                       ORDER BY cl.id DESC
                       LIMIT 1
                   ) AS last_log_status,
                   (
                       SELECT cl.new_jobs_count
                       FROM crawl_logs cl
                       JOIN watch_sources ws ON ws.id = cl.source_id
                       WHERE ws.platform = gs.platform
                         AND ws.source_type = gs.source_type
                         AND ws.url = gs.url
                       ORDER BY cl.id DESC
                       LIMIT 1
                   ) AS last_new_jobs_count,
                   (
                       SELECT cl.error_message
                       FROM crawl_logs cl
                       JOIN watch_sources ws ON ws.id = cl.source_id
                       WHERE ws.platform = gs.platform
                         AND ws.source_type = gs.source_type
                         AND ws.url = gs.url
                       ORDER BY cl.id DESC
                       LIMIT 1
                   ) AS last_error_message,
                   (
                       SELECT cl.duration_ms
                       FROM crawl_logs cl
                       JOIN watch_sources ws ON ws.id = cl.source_id
                       WHERE ws.platform = gs.platform
                         AND ws.source_type = gs.source_type
                         AND ws.url = gs.url
                       ORDER BY cl.id DESC
                       LIMIT 1
                   ) AS last_duration_ms
            FROM grouped_sources gs
            ORDER BY
                CASE gs.status WHEN 'error' THEN 0 ELSE 1 END,
                gs.platform,
                gs.id
            """
        ).fetchall()
    )


def dashboard_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    job_count = conn.execute("SELECT COUNT(*) AS count FROM detected_jobs").fetchone()["count"]
    high_score_count = conn.execute(
        "SELECT COUNT(*) AS count FROM detected_jobs WHERE score >= 12"
    ).fetchone()["count"]
    log_count = conn.execute("SELECT COUNT(*) AS count FROM crawl_logs").fetchone()["count"]
    last_log = conn.execute(
        """
        SELECT crawled_at, status, new_jobs_count, error_message
        FROM crawl_logs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    return {
        "job_count": job_count,
        "high_score_count": high_score_count,
        "log_count": log_count,
        "last_log": dict(last_log) if last_log else None,
    }


def parse_raw_data(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def first_raw_value(record: dict[str, Any], aliases: tuple[str, ...]) -> str:
    lowered = {str(key).lower(): value for key, value in record.items()}
    for alias in aliases:
        value = record.get(alias)
        if value not in (None, ""):
            return clean_raw_value(value)
        value = lowered.get(alias.lower())
        if value not in (None, ""):
            return clean_raw_value(value)
    return ""


def clean_raw_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(clean_raw_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return " ".join(str(value).split())


def build_alio_detail_url(source_record_id: str) -> str:
    record_id = "".join(ch for ch in str(source_record_id or "") if ch.isdigit())
    if not record_id:
        return ""
    return f"{ALIO_RECRUIT_DETAIL_BASE_URL}?sn={record_id}"


UI_TITLE_BLACKLIST = ("스크랩", "관심등록", "입사지원", "즉시지원", "즐겨찾기")

FALLBACK_COMPANY_NAMES = ("잡코리아", "사람인")

FILLER_FIELD_VALUES = ("잡코리아 공개 채용목록", "사람인 공개 채용목록")


def normalize_company(name: str | None) -> str:
    text = str(name or "")
    text = re.sub(r"\(주\)|\(유\)|\(재\)|\(사\)|㈜|주식회사|유한회사", "", text)
    return re.sub(r"\s+", "", text).lower()


def dedupe_group_key(company_name: str | None, title: str | None) -> str:
    company = normalize_company(company_name)
    title_text = re.sub(r"[\s\[\]()/,.·~‧・&+'\"-]+", "", str(title or "")).lower()
    if not company or not title_text:
        return ""
    return f"{company}|{title_text}"


def cleanup_jobs(conn: sqlite3.Connection, *, apply: bool = False) -> dict[str, int]:
    """재수집으로도 교정되지 않은 오염 행을 정리한다.

    - 제목이 UI 버튼 텍스트("스크랩" 등)로 잘못 저장된 행 삭제
    - 회사명이 플랫폼 폴백("잡코리아"/"사람인")으로 저장된 행 삭제
    - field에 남은 필러 문구는 빈 값으로 갱신
    """
    title_marks = ",".join("?" for _ in UI_TITLE_BLACKLIST)
    company_marks = ",".join("?" for _ in FALLBACK_COMPANY_NAMES)
    field_marks = ",".join("?" for _ in FILLER_FIELD_VALUES)
    bad_title_count = conn.execute(
        f"SELECT COUNT(*) AS c FROM detected_jobs WHERE title IN ({title_marks})",
        UI_TITLE_BLACKLIST,
    ).fetchone()["c"]
    bad_company_count = conn.execute(
        f"SELECT COUNT(*) AS c FROM detected_jobs WHERE company_name IN ({company_marks})",
        FALLBACK_COMPANY_NAMES,
    ).fetchone()["c"]
    filler_field_count = conn.execute(
        f"SELECT COUNT(*) AS c FROM detected_jobs WHERE field IN ({field_marks})",
        FILLER_FIELD_VALUES,
    ).fetchone()["c"]
    if apply:
        conn.execute(
            f"DELETE FROM detected_jobs WHERE title IN ({title_marks})",
            UI_TITLE_BLACKLIST,
        )
        conn.execute(
            f"DELETE FROM detected_jobs WHERE company_name IN ({company_marks})",
            FALLBACK_COMPANY_NAMES,
        )
        conn.execute(
            f"UPDATE detected_jobs SET field = '' WHERE field IN ({field_marks})",
            FILLER_FIELD_VALUES,
        )
        conn.commit()
    return {
        "bad_title": bad_title_count,
        "fallback_company": bad_company_count,
        "filler_field": filler_field_count,
    }


def build_unique_key(
    *,
    source_platform: str = "",
    source_record_id: str,
    company_name: str | None,
    title: str | None,
    deadline: str | None,
    url: str | None,
) -> str:
    if source_record_id:
        base = f"{source_platform or 'unknown'}|{source_record_id}"
    else:
        base = "|".join([company_name or "", title or "", deadline or "", url or ""])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()
