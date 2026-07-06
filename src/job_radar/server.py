from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from zoneinfo import ZoneInfo

from .company_client import load_company_targets
from .config import load_keywords, load_settings
from .crawler import run_all_crawlers
from .dashboard import render_dashboard
from .db import connect, dashboard_summary, init_db, list_jobs, list_logs, list_source_health


KST = ZoneInfo("Asia/Seoul")


class JobRadarServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        interval_hours: int = 6,
        run_on_start: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.interval_hours = interval_hours
        self.run_on_start = run_on_start
        self.settings = load_settings()
        self.rules = load_keywords()
        self.lock = threading.Lock()
        self.last_result: dict[str, Any] = {}
        self.next_run_at = next_kst_boundary(interval_hours)

    def serve_forever(self) -> None:
        server_state = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path.startswith("/api/jobs"):
                    self.respond_json(server_state.jobs_payload())
                    return
                if self.path.startswith("/api/status"):
                    self.respond_json(server_state.status_payload())
                    return
                self.respond_html(server_state.dashboard_html())

            def do_POST(self) -> None:
                if self.path.startswith("/run-crawl"):
                    result = server_state.run_crawl()
                    self.respond_json(
                        {
                            "message": (
                                f"수집 완료: fetched={result.get('fetched')}, "
                                f"inserted={result.get('inserted')}"
                            ),
                            "result": result,
                        }
                    )
                    return
                self.send_error(404)

            def log_message(self, format: str, *args: Any) -> None:
                timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
                print(f"[{timestamp}] {self.address_string()} {format % args}")

            def respond_html(self, body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def respond_json(self, data: dict[str, Any] | list[Any]) -> None:
                encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        threading.Thread(target=self.scheduler_loop, daemon=True).start()
        httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"Serving 채용 공고 at http://{self.host}:{self.port}")
        print(f"Next auto crawl: {format_kst(self.next_run_at)}")
        httpd.serve_forever()

    def scheduler_loop(self) -> None:
        if self.run_on_start:
            self.run_crawl()
        while True:
            now = datetime.now(KST)
            if now >= self.next_run_at:
                self.run_crawl()
                self.next_run_at = next_kst_boundary(self.interval_hours)
            time.sleep(30)

    def run_crawl(self) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            return {"status": "already_running", "message": "이미 수집 중입니다."}
        try:
            with connect(self.settings.db_path) as conn:
                init_db(conn)
                result = run_all_crawlers(conn, settings=self.settings, rules=self.rules)
            payload = {
                "status": "done",
                "fetched": result.fetched,
                "candidates": result.candidates,
                "inserted": result.inserted,
                "errors": result.errors or [],
                "finished_at_kst": format_kst(datetime.now(KST)),
            }
            self.last_result = payload
            self.next_run_at = next_kst_boundary(self.interval_hours)
            return payload
        finally:
            self.lock.release()

    def dashboard_html(self) -> str:
        with connect(self.settings.db_path) as conn:
            init_db(conn)
            return render_dashboard(
                dashboard_summary(conn),
                list_jobs(conn, limit=None),
                list_logs(conn, limit=30),
                self.visible_source_health(list_source_health(conn)),
                next_run_kst=format_kst(self.next_run_at),
                auto_refresh=True,
            )

    def jobs_payload(self) -> list[dict[str, Any]]:
        with connect(self.settings.db_path) as conn:
            init_db(conn)
            return [dict(row) for row in list_jobs(conn, limit=None)]

    def status_payload(self) -> dict[str, Any]:
        return {
            "next_run_kst": format_kst(self.next_run_at),
            "last_result": self.last_result,
        }

    def visible_source_health(self, rows: list[Any]) -> list[Any]:
        disabled_company_urls = {
            target.url
            for target in load_company_targets(self.settings.company_targets_path, include_disabled=True)
            if not target.enabled
        }
        visible = []
        for row in rows:
            platform = str(row["platform"] or "").lower()
            if platform == "worknet" and not self.settings.worknet_enabled:
                continue
            if platform == "company" and row["url"] in disabled_company_urls:
                continue
            visible.append(row)
        return visible


def next_kst_boundary(interval_hours: int) -> datetime:
    now = datetime.now(KST)
    base = now.replace(minute=0, second=0, microsecond=0)
    next_hour = ((base.hour // interval_hours) + 1) * interval_hours
    if next_hour >= 24:
        return (base + timedelta(days=1)).replace(hour=0)
    return base.replace(hour=next_hour)


def format_kst(value: datetime) -> str:
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def run_server(*, host: str = "127.0.0.1", port: int = 8787, run_on_start: bool = True) -> None:
    JobRadarServer(host=host, port=port, run_on_start=run_on_start).serve_forever()
