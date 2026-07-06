from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import dedupe_group_key


KST = ZoneInfo("Asia/Seoul")


def render_dashboard(
    summary: dict[str, Any],
    jobs: list[Any],
    logs: list[Any],
    source_health: list[Any] | None = None,
    *,
    next_run_kst: str = "",
    auto_refresh: bool = False,
) -> str:
    job_dicts = merge_duplicate_jobs([dict(row) for row in jobs])
    payload_jobs = [serialize_job(row) for row in job_dicts]
    job_payload = json.dumps(payload_jobs, ensure_ascii=False)
    log_rows = "\n".join(render_log_row(dict(row)) for row in logs)
    source_rows = "\n".join(render_source_row(dict(row)) for row in (source_health or []))
    sources = sorted(
        {
            label
            for job in payload_jobs
            for label in str(job.get("source_label", "")).split("·")
            if label
        }
    )
    source_options = "\n".join(
        f'<option value="{escape(source)}">{escape(source)}</option>' for source in sources
    )
    last_log = summary.get("last_log") or {}
    last_status_html = status_badge(str(last_log.get("status", "없음") or "없음"))
    crawl_button = (
        '<button type="button" class="ghost" onclick="runCrawl(this)">지금 수집</button>'
        if auto_refresh
        else ""
    )
    generated_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    next_run_html = (
        f'<span class="meta-item">다음 자동 수집 {escape(next_run_kst)}</span>' if next_run_kst else ""
    )

    return (
        DASHBOARD_TEMPLATE.replace("__JOB_PAYLOAD__", job_payload)
        .replace("__SOURCE_OPTIONS__", source_options)
        .replace("__SOURCE_ROWS__", source_rows)
        .replace("__LOG_ROWS__", log_rows)
        .replace("__LAST_STATUS__", last_status_html)
        .replace("__CRAWL_BUTTON__", crawl_button)
        .replace("__GENERATED_AT__", escape(generated_at))
        .replace("__NEXT_RUN__", next_run_html)
    )


DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>기계직 채용 레이더</title>
  <style>
    :root {
      --ink: #1a2233;
      --muted: #66738c;
      --line: #e3e9f2;
      --bg: #f4f6fa;
      --card: #ffffff;
      --accent: #0f2d52;
      --link: #0b63ce;
      --ok: #087a4a;
      --warn: #a15c00;
      --danger: #c21f32;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", sans-serif;
      background: var(--bg);
      color: var(--ink);
      font-size: 14px;
    }
    header {
      background: var(--accent);
      color: white;
      padding: 18px 20px;
    }
    header h1 { margin: 0; font-size: 19px; }
    header .meta { margin-top: 6px; font-size: 12px; opacity: 0.85; display: flex; gap: 14px; flex-wrap: wrap; }
    main { max-width: 980px; margin: 0 auto; padding: 16px; }
    a { color: var(--link); text-decoration: none; }
    a:hover { text-decoration: underline; }

    .stats { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
    .stat {
      flex: 1 1 120px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 14px;
    }
    .stat .label { font-size: 12px; color: var(--muted); }
    .stat strong { display: block; font-size: 22px; margin-top: 2px; }
    .stat.danger strong { color: var(--danger); }
    .stat.ok strong { color: var(--ok); }

    .tabs { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
    .tab {
      border: 1px solid var(--line);
      background: var(--card);
      color: var(--muted);
      border-radius: 999px;
      padding: 7px 16px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }
    .tab.active { background: var(--accent); border-color: var(--accent); color: white; }
    .tab .count { font-weight: 400; opacity: 0.8; margin-left: 4px; }

    .controls { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .controls input[type="search"] {
      flex: 2 1 220px;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 12px;
      font: inherit;
      background: var(--card);
    }
    .controls select {
      flex: 1 1 130px;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      font: inherit;
      background: var(--card);
    }
    .controls label.toggle {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 0 10px;
      font-size: 13px;
      color: var(--muted);
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 38px;
      cursor: pointer;
      white-space: nowrap;
    }
    button.ghost {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--card);
      color: var(--accent);
      font: inherit;
      font-weight: 700;
      padding: 0 14px;
      cursor: pointer;
    }

    .company-group {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      margin-bottom: 8px;
      overflow: hidden;
    }
    .company-group > summary {
      list-style: none;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      cursor: pointer;
      flex-wrap: wrap;
    }
    .company-group > summary::-webkit-details-marker { display: none; }
    .company-group > summary::before {
      content: "▸";
      color: var(--muted);
      font-size: 12px;
      transition: transform 0.15s;
    }
    .company-group[open] > summary::before { transform: rotate(90deg); }
    .company-name { font-weight: 800; font-size: 14px; }
    .job-count { color: var(--muted); font-size: 12px; }
    .postings { border-top: 1px solid var(--line); }

    .posting {
      display: flex;
      align-items: baseline;
      gap: 10px;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
      flex-wrap: wrap;
    }
    .posting:last-child { border-bottom: none; }
    .posting .title { flex: 1 1 300px; font-weight: 600; }
    .posting .sub { color: var(--muted); font-size: 12px; white-space: nowrap; }
    .single .posting { border-bottom: none; }
    .single > summary { display: none; }

    .chip {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 800;
      white-space: nowrap;
    }
    .chip.new { background: #e7f7ef; color: var(--ok); }
    .chip.dday { background: #fde8e8; color: var(--danger); }
    .chip.dday-soon { background: #fff3d7; color: var(--warn); }
    .chip.ongoing { background: #edf2f7; color: var(--muted); font-weight: 600; }
    .chip.watch { background: #eef2ff; color: #3730a3; }
    .chip.source { background: #edf4ff; color: #174b8f; font-weight: 600; }
    .chip.career { background: #f4f0ff; color: #5b3fa8; font-weight: 600; }

    .empty {
      text-align: center;
      color: var(--muted);
      padding: 40px 0;
    }
    .more-bar {
      width: 100%;
      margin: 4px 0 16px;
      min-height: 40px;
      border: 1px dashed var(--line);
      border-radius: 10px;
      background: transparent;
      color: var(--muted);
      font: inherit;
      cursor: pointer;
    }

    details.aux {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 10px;
      margin-top: 14px;
      padding: 0;
    }
    details.aux > summary {
      padding: 12px 14px;
      cursor: pointer;
      font-weight: 700;
      color: var(--muted);
      font-size: 13px;
    }
    details.aux .table-wrap { overflow-x: auto; padding: 0 14px 14px; }
    details.aux table { width: 100%; border-collapse: collapse; font-size: 12px; min-width: 720px; }
    details.aux th, details.aux td { border-bottom: 1px solid var(--line); padding: 8px 6px; text-align: left; vertical-align: top; }
    details.aux th { color: var(--muted); white-space: nowrap; }
    .url-cell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }
    .status-pill::before { content: ""; width: 8px; height: 8px; border-radius: 999px; background: currentColor; }
    .status-ok { background: #e7f7ef; color: var(--ok); }
    .status-warn { background: #fff3d7; color: var(--warn); }
    .status-error { background: #fde8e8; color: var(--danger); }
    .status-idle { background: #edf2f7; color: var(--muted); }
  </style>
</head>
<body>
  <header>
    <h1>기계직 채용 레이더</h1>
    <div class="meta">
      <span class="meta-item">생성 __GENERATED_AT__</span>
      __NEXT_RUN__
      <span class="meta-item">최근 수집 __LAST_STATUS__</span>
    </div>
  </header>
  <main>
    <div class="stats">
      <div class="stat ok"><span class="label">기계직 공고</span><strong id="statMech">0</strong></div>
      <div class="stat"><span class="label">오늘 신규</span><strong id="statNew">0</strong></div>
      <div class="stat danger"><span class="label">7일 내 마감</span><strong id="statClosing">0</strong></div>
      <div class="stat"><span class="label">전체 저장</span><strong id="statTotal">0</strong></div>
    </div>

    <div class="tabs" id="tabs">
      <button class="tab active" data-tab="mech">기계직<span class="count" id="cntMech"></span></button>
      <button class="tab" data-tab="review">참고<span class="count" id="cntReview"></span></button>
      <button class="tab" data-tab="watch">관심기업<span class="count" id="cntWatch"></span></button>
      <button class="tab" data-tab="all">전체<span class="count" id="cntAll"></span></button>
    </div>

    <div class="controls">
      <input type="search" id="q" placeholder="회사·제목·분야 검색">
      <select id="source">
        <option value="">모든 출처</option>
        __SOURCE_OPTIONS__
      </select>
      <select id="sort">
        <option value="new">신규 수집순</option>
        <option value="deadline">마감 임박순</option>
      </select>
      <label class="toggle"><input type="checkbox" id="hideExpired" checked>마감 지난 공고 숨기기</label>
      __CRAWL_BUTTON__
    </div>

    <div id="groups"></div>
    <button class="more-bar" id="moreBar" hidden onclick="showMore()">더 보기</button>

    <details class="aux">
      <summary>수집 소스 상태</summary>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>출처</th><th>상태</th><th>최근 수집</th><th>신규</th><th>누적 오류</th><th>소요</th><th>URL</th><th>메시지</th></tr>
          </thead>
          <tbody>
__SOURCE_ROWS__
          </tbody>
        </table>
      </div>
    </details>

    <details class="aux">
      <summary>최근 수집 로그</summary>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>시각</th><th>상태</th><th>신규</th><th>소요(ms)</th><th>메시지</th></tr>
          </thead>
          <tbody>
__LOG_ROWS__
          </tbody>
        </table>
      </div>
    </details>
  </main>

  <script>
    const JOBS = __JOB_PAYLOAD__;
    const GROUP_PAGE = 40;
    const state = { tab: "mech", q: "", source: "", sort: "new", hideExpired: true, visibleGroups: GROUP_PAGE };

    const NOW = Date.now();
    const DAY = 24 * 60 * 60 * 1000;

    function detectedTs(job) {
      if (!job.detected_at) return 0;
      const ts = Date.parse(job.detected_at.replace(" ", "T") + "Z"); // SQLite CURRENT_TIMESTAMP = UTC
      return Number.isNaN(ts) ? 0 : ts;
    }

    function deadlineDays(job) {
      const raw = String(job.deadline || "").trim();
      if (!raw) return null;
      if (/상시|수시|채용\\s*시|충원\\s*시/.test(raw)) return null;
      if (raw.includes("오늘마감")) return 0;
      if (raw.includes("내일마감")) return 1;
      let m = raw.match(/^D-(\\d+)/i);
      if (m) return parseInt(m[1], 10);
      m = raw.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (!m) m = raw.match(/(\\d{4})(\\d{2})(\\d{2})/);
      if (m) return daysUntil(new Date(+m[1], +m[2] - 1, +m[3]));
      m = raw.match(/(\\d{1,2})[./](\\d{1,2})/);
      if (m) {
        const now = new Date();
        let d = new Date(now.getFullYear(), +m[1] - 1, +m[2]);
        if ((now - d) / DAY > 60) d = new Date(now.getFullYear() + 1, +m[1] - 1, +m[2]);
        return daysUntil(d);
      }
      return null;
    }

    function daysUntil(date) {
      const today = new Date();
      const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      return Math.round((date - start) / DAY);
    }

    function isNew(job) { return NOW - detectedTs(job) < 2 * DAY; }
    function isToday(job) { return NOW - detectedTs(job) < 1 * DAY; }

    function tabMatch(job, tab) {
      if (tab === "mech") return job.fit_level === "기계직";
      if (tab === "review") return job.fit_level === "참고";
      if (tab === "watch") return Boolean(job.watch_grade);
      return true;
    }

    function jobMatches(job) {
      if (!tabMatch(job, state.tab)) return false;
      if (state.source && !String(job.source_label).split("·").includes(state.source)) return false;
      if (state.hideExpired) {
        const days = deadlineDays(job);
        if (days !== null && days < 0) return false;
      }
      if (state.q) {
        const hay = (job.company_name + " " + job.title + " " + (job.field || "")).toLowerCase();
        for (const token of state.q.toLowerCase().split(/\\s+/)) {
          if (token && !hay.includes(token)) return false;
        }
      }
      return true;
    }

    function bestLink(job) {
      return job.external_url || job.url || job.alio_detail_url || "";
    }

    function ddayChip(job) {
      const days = deadlineDays(job);
      if (days === null) {
        const raw = String(job.deadline || "").trim();
        return raw ? `<span class="chip ongoing">${escapeHtml(raw)}</span>` : "";
      }
      if (days < 0) return `<span class="chip ongoing">마감</span>`;
      const label = days === 0 ? "오늘 마감" : `D-${days}`;
      const cls = days <= 3 ? "dday" : (days <= 10 ? "dday-soon" : "ongoing");
      return `<span class="chip ${cls}">${label}</span>`;
    }

    function postingHtml(job) {
      const link = bestLink(job);
      const title = link
        ? `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${escapeHtml(job.title)}</a>`
        : escapeHtml(job.title);
      const chips = [
        isNew(job) ? '<span class="chip new">NEW</span>' : "",
        ddayChip(job),
        job.career_type ? `<span class="chip career">${escapeHtml(job.career_type)}</span>` : "",
        `<span class="chip source">${escapeHtml(job.source_label)}</span>`,
      ].filter(Boolean).join(" ");
      const sub = [job.location, job.field].filter(Boolean).join(" · ");
      return `<div class="posting">
        <span class="title">${title}</span>
        ${sub ? `<span class="sub">${escapeHtml(sub)}</span>` : ""}
        <span class="chips">${chips}</span>
      </div>`;
    }

    function render() {
      const rows = JOBS.filter(jobMatches);

      document.getElementById("statMech").textContent = JOBS.filter(j => j.fit_level === "기계직").length;
      document.getElementById("statNew").textContent = JOBS.filter(isToday).length;
      document.getElementById("statClosing").textContent = JOBS.filter(j => {
        const d = deadlineDays(j);
        return j.fit_level === "기계직" && d !== null && d >= 0 && d <= 7;
      }).length;
      document.getElementById("statTotal").textContent = JOBS.length;
      document.getElementById("cntMech").textContent = JOBS.filter(j => tabMatch(j, "mech")).length;
      document.getElementById("cntReview").textContent = JOBS.filter(j => tabMatch(j, "review")).length;
      document.getElementById("cntWatch").textContent = JOBS.filter(j => tabMatch(j, "watch")).length;
      document.getElementById("cntAll").textContent = JOBS.length;

      const groups = new Map();
      for (const job of rows) {
        const key = job.company_name || "회사명 미확인";
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(job);
      }
      let entries = [...groups.entries()];
      const groupNewest = list => Math.max(...list.map(detectedTs));
      const groupDeadline = list => {
        const days = list.map(deadlineDays).filter(d => d !== null && d >= 0);
        return days.length ? Math.min(...days) : 9999;
      };
      if (state.sort === "deadline") {
        entries.sort((a, b) => groupDeadline(a[1]) - groupDeadline(b[1]));
      } else {
        entries.sort((a, b) => groupNewest(b[1]) - groupNewest(a[1]));
      }
      for (const [, list] of entries) {
        list.sort((a, b) => {
          const da = deadlineDays(a), db = deadlineDays(b);
          return (da === null ? 9999 : da) - (db === null ? 9999 : db);
        });
      }

      const visible = entries.slice(0, state.visibleGroups);
      const container = document.getElementById("groups");
      if (!rows.length) {
        container.innerHTML = '<div class="empty">조건에 맞는 공고가 없습니다.</div>';
      } else {
        container.innerHTML = visible.map(([company, list]) => {
          const watch = list.find(j => j.watch_label);
          const watchChip = watch ? `<span class="chip watch">관심 ${escapeHtml(watch.watch_grade)}</span>` : "";
          const hasNew = list.some(isNew) ? '<span class="chip new">NEW</span>' : "";
          const near = ddayChipForGroup(list);
          if (list.length === 1) {
            return `<details class="company-group single" open>
              <summary></summary>
              <div class="postings">
                <div class="posting">
                  <span class="title"><strong>${escapeHtml(company)}</strong> — ${titleLink(list[0])}</span>
                  <span class="chips">${postingChips(list[0])} ${watchChip}</span>
                </div>
              </div>
            </details>`;
          }
          return `<details class="company-group">
            <summary>
              <span class="company-name">${escapeHtml(company)}</span>
              <span class="job-count">${list.length}건</span>
              ${watchChip} ${hasNew} ${near}
            </summary>
            <div class="postings">${list.map(postingHtml).join("")}</div>
          </details>`;
        }).join("");
      }
      document.getElementById("moreBar").hidden = entries.length <= state.visibleGroups;
      document.getElementById("moreBar").textContent = `더 보기 (${entries.length - state.visibleGroups}개 회사 남음)`;
    }

    function titleLink(job) {
      const link = bestLink(job);
      return link
        ? `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${escapeHtml(job.title)}</a>`
        : escapeHtml(job.title);
    }

    function postingChips(job) {
      return [
        isNew(job) ? '<span class="chip new">NEW</span>' : "",
        ddayChip(job),
        job.career_type ? `<span class="chip career">${escapeHtml(job.career_type)}</span>` : "",
        `<span class="chip source">${escapeHtml(job.source_label)}</span>`,
      ].filter(Boolean).join(" ");
    }

    function ddayChipForGroup(list) {
      const days = list.map(deadlineDays).filter(d => d !== null && d >= 0);
      if (!days.length) return "";
      const min = Math.min(...days);
      if (min > 10) return "";
      const cls = min <= 3 ? "dday" : "dday-soon";
      return `<span class="chip ${cls}">${min === 0 ? "오늘 마감" : `D-${min}`}</span>`;
    }

    function showMore() {
      state.visibleGroups += GROUP_PAGE;
      render();
    }

    function escapeHtml(value) {
      return String(value == null ? "" : value)
        .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
    }

    async function runCrawl(button) {
      button.disabled = true;
      button.textContent = "수집 중...";
      try {
        const res = await fetch("/run-crawl", { method: "POST" });
        await res.json();
        location.reload();
      } catch (err) {
        button.textContent = "실패 — 다시 시도";
        button.disabled = false;
      }
    }

    document.getElementById("tabs").addEventListener("click", (event) => {
      const tab = event.target.closest(".tab");
      if (!tab) return;
      state.tab = tab.dataset.tab;
      state.visibleGroups = GROUP_PAGE;
      document.querySelectorAll(".tab").forEach(el => el.classList.toggle("active", el === tab));
      render();
    });
    document.getElementById("q").addEventListener("input", (event) => {
      state.q = event.target.value.trim();
      state.visibleGroups = GROUP_PAGE;
      render();
    });
    document.getElementById("source").addEventListener("change", (event) => {
      state.source = event.target.value;
      state.visibleGroups = GROUP_PAGE;
      render();
    });
    document.getElementById("sort").addEventListener("change", (event) => {
      state.sort = event.target.value;
      render();
    });
    document.getElementById("hideExpired").addEventListener("change", (event) => {
      state.hideExpired = event.target.checked;
      render();
    });

    render();
  </script>
</body>
</html>
"""


def merge_duplicate_jobs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 회사+제목 공고를 하나로 묶고 출처를 병합한다. 원본 DB 행은 건드리지 않는다."""
    merged: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    fill_fields = (
        "deadline",
        "career_type",
        "employment_type",
        "location",
        "field",
        "external_url",
        "posted_date",
    )
    for row in rows:
        key = dedupe_group_key(row.get("company_name"), row.get("title"))
        if not key:
            merged.append(row)
            continue
        existing = by_key.get(key)
        if existing is None:
            row["_source_platforms"] = [str(row.get("source_platform") or "")]
            by_key[key] = row
            merged.append(row)
            continue
        platform = str(row.get("source_platform") or "")
        if platform and platform not in existing["_source_platforms"]:
            existing["_source_platforms"].append(platform)
        if int(row.get("score") or 0) > int(existing.get("score") or 0):
            existing["score"] = row.get("score")
            existing["matched_keywords"] = row.get("matched_keywords")
        for field in fill_fields:
            if not existing.get(field) and row.get(field):
                existing[field] = row[field]
    return merged


def serialize_job(row: dict[str, Any]) -> dict[str, Any]:
    fit = classify_mechanical_fit(row)
    watch = watch_info(row)
    watch_grade = watch.get("watchGrade", "")
    watch_name = watch.get("name", "")
    platforms = row.get("_source_platforms") or [row.get("source_platform")]
    merged_source = "·".join(source_label(platform) for platform in platforms if platform)
    return {
        "score": row.get("score"),
        "source_label": merged_source or source_label(row.get("source_platform")),
        "fit_level": fit["level"],
        "fit_class": fit["class"],
        "fit_reasons": ", ".join(fit["reasons"]),
        "sector_label": classify_sector(row),
        "watch_grade": watch_grade,
        "watch_label": f"{watch_grade} {watch_name}".strip(),
        "company_name": row.get("company_name") or "",
        "title": row.get("title") or "",
        "deadline": row.get("deadline") or "",
        "career_type": row.get("career_type") or "",
        "employment_type": row.get("employment_type") or "",
        "location": row.get("location") or "",
        "field": row.get("field") or "",
        "detected_at": row.get("detected_at") or "",
        "url": row.get("url") or "",
        "alio_detail_url": row.get("alio_detail_url") or "",
        "external_url": row.get("external_url") or "",
    }


def watch_info(row: dict[str, Any]) -> dict[str, str]:
    watch = raw_data_of(row).get("companyWatchlist")
    if not isinstance(watch, dict):
        return {}
    return {str(key): str(value or "") for key, value in watch.items()}


def render_source_row(row: dict[str, Any]) -> str:
    status = str(row.get("last_log_status") or row.get("status") or "")
    duration = row.get("last_duration_ms")
    duration_text = f"{duration}ms" if duration not in (None, "") else ""
    new_jobs = row.get("last_new_jobs_count")
    return f"""<tr>
  <td>{escape(source_label(row.get("platform")) or row.get("platform") or "")}</td>
  <td>{status_badge(status)}</td>
  <td>{escape(row.get("last_crawled_at") or "")}</td>
  <td>{escape("" if new_jobs is None else new_jobs)}</td>
  <td>{escape(row.get("error_count") or 0)}</td>
  <td>{escape(duration_text)}</td>
  <td class="url-cell"><a href="{escape(row.get("url") or "")}" target="_blank" rel="noreferrer">{escape(row.get("url") or "")}</a></td>
  <td>{escape(row.get("last_error_message") or "")}</td>
</tr>"""


# 기계직 확정 단어 — 직무를 직접 가리키는 단어만 넣는다 (제목/모집분야에서만 찾음)
MECH_STRONG_TERMS = (
    "기계",
    "기구설계",
    "기구개발",
    "설비",
    "보전",
    "정비",
    "유지보수",
    "공무",
    "생산기술",
    "공정기술",
    "제조기술",
    "플랜트",
    "금형",
    "용접",
    "배관",
    "공조",
    "냉동",
    "보일러",
    "사출",
    "절삭",
    "선반",
    "밀링",
    "프레스",
    "cnc",
    "mct",
    "치공구",
    "발전설비",
    "유틸리티",
    "utility",
    "maintenance",
    "자동화설비",
    "로봇",
    "철도차량",
    "중장비",
    "건설기계",
)

# 참고 단어 — 기계직일 수도 있는 넓은 직무 단어
MECH_BROAD_TERMS = (
    "생산",
    "제조",
    "공정",
    "품질",
    "안전관리",
    "시설관리",
    "장비",
    "설계",
    "엔지니어",
    "기술직",
    "연구개발",
    "r&d",
    "cad",
    "도면",
)

# 무관 확정 단어 — 이 단어가 있고 기계직 단어가 없으면 무관 처리
MECH_REJECT_TERMS = (
    "마케팅",
    "영업",
    "회계",
    "세무",
    "재무",
    "인사",
    "노무",
    "총무",
    "경리",
    "사무직",
    "행정",
    "비서",
    "소프트웨어",
    "프론트엔드",
    "백엔드",
    "앱개발",
    "웹개발",
    "데이터분석",
    "디자이너",
    "디자인",
    "브랜드",
    "콘텐츠",
    "에디터",
    "카피라이터",
    "교사",
    "강사",
    "교육",
    "상담",
    "간호",
    "요양",
    "약사",
    "임상",
    "조리",
    "주방",
    "서빙",
    "미용",
    "판매",
    "매장",
    "캐셔",
    "텔레마케팅",
    "고객센터",
    "배송",
    "택배",
    "운전원",
    "경비",
    "미화",
    "보험",
    "금융",
    "은행",
    "호텔",
    "물류관리",
    "마케터",
    "세일즈",
    "sales",
    "바리스타",
    "영양사",
    "급식",
    "조무사",
    "사서",
    "통역",
    "번역",
    "인플루언서",
    "쇼호스트",
    "회계사",
    "변호사",
    "법무",
)

# 기계 카테고리 목록에서 왔을 때 기계직으로 승격해도 안전한 넓은 단어
# ("엔지니어", "품질" 등은 AI 엔지니어/식품 품질처럼 오탐이 많아 제외)
MECH_PROMOTABLE_BROAD_TERMS = ("생산", "제조", "공정", "장비", "설계", "기술직")

MECHANICAL_LIST_CATEGORIES = ("기계 직무 목록",)
RELATED_LIST_CATEGORIES = ("생산 직무 목록", "연구 직무 목록")

FIT_MECH = "기계직"
FIT_REVIEW = "참고"
FIT_NONE = "무관"


def classify_mechanical_fit(row: dict[str, Any]) -> dict[str, Any]:
    """제목·모집분야 텍스트와 수집 목록 카테고리로 기계직 여부를 3단계로 나눈다.

    회사명은 오탐이 많아 매칭에서 제외한다 (예: "동양기계공업"의 사무직 공고).
    """
    text = " ".join(
        str(row.get(key) or "") for key in ("title", "field")
    ).lower()
    category = str(raw_data_of(row).get("listCategory") or "")

    # "공무원"/"공무직"의 "공무"는 설비공무가 아니므로 매칭 대상에서 제거
    strong_text = text.replace("공무원", "").replace("공무직", "")
    strong_hits = [term for term in MECH_STRONG_TERMS if term in strong_text]
    broad_hits = [term for term in MECH_BROAD_TERMS if term in text]
    reject_hits = [term for term in MECH_REJECT_TERMS if term in text]

    if strong_hits:
        return {"level": FIT_MECH, "class": "fit-strong", "reasons": strong_hits[:5]}
    if reject_hits:
        return {"level": FIT_NONE, "class": "fit-low", "reasons": reject_hits[:3]}
    if broad_hits:
        promotable = [term for term in broad_hits if term in MECH_PROMOTABLE_BROAD_TERMS]
        if promotable and category in MECHANICAL_LIST_CATEGORIES:
            return {"level": FIT_MECH, "class": "fit-strong", "reasons": promotable[:5] + [category]}
        return {"level": FIT_REVIEW, "class": "fit-review", "reasons": broad_hits[:5]}
    if category in MECHANICAL_LIST_CATEGORIES + RELATED_LIST_CATEGORIES:
        return {"level": FIT_REVIEW, "class": "fit-review", "reasons": [category]}
    return {"level": FIT_NONE, "class": "fit-low", "reasons": []}


def raw_data_of(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_data")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def classify_sector(row: dict[str, Any]) -> str:
    platform = str(row.get("source_platform") or "").lower()
    text = " ".join(
        str(row.get(key) or "")
        for key in ("company_name", "title", "field", "employment_type", "career_type")
    )
    civil_tokens = ("공무원", "임기제", "지방직", "국가직", "공무직", "군무원")
    public_tokens = (
        "공사",
        "공단",
        "공공",
        "재단",
        "진흥원",
        "정부",
        "시청",
        "군청",
        "구청",
        "도청",
        "교육청",
        "한국",
    )
    if any(token in text for token in civil_tokens):
        return "공무원/공무직"
    if platform == "alio":
        return "공기업/공공기관"
    if any(token in text for token in public_tokens):
        return "공기업/공공기관"
    if platform in ("jobkorea", "saramin", "jasoseol", "worknet", "company"):
        return "사기업/민간"
    return "기타"


def source_label(value: Any) -> str:
    labels = {
        "alio": "ALIO",
        "jobkorea": "잡코리아",
        "saramin": "사람인",
        "jasoseol": "자소설닷컴",
        "worknet": "워크넷",
        "company": "기업 직접",
    }
    return labels.get(str(value or "").lower(), value or "")


def status_badge(status: str) -> str:
    return (
        f'<span class="status-pill {escape(status_badge_class(status))}">'
        f"{escape(status_label(status))}</span>"
    )


def status_badge_class(status: str) -> str:
    lowered = status.lower()
    if any(token in lowered for token in ("success", "done")):
        return "status-ok"
    if any(token in lowered for token in ("blocked", "already", "dry_run")):
        return "status-warn"
    if any(token in lowered for token in ("fail", "error")):
        return "status-error"
    return "status-idle"


def status_label(status: str) -> str:
    labels = {
        "public_success": "ALIO 정상",
        "platform_success": "플랫폼 정상",
        "company_success": "기업 직접 정상",
        "company_success_dry_run": "기업 직접 점검",
        "worknet_success": "워크넷 정상",
        "jasoseol_success": "자소설닷컴 정상",
        "jasoseol_success_dry_run": "자소설닷컴 점검",
        "success": "정상",
        "done": "완료",
        "platform_blocked": "robots 차단",
        "company_blocked": "robots 차단 (기업 직접)",
        "jasoseol_blocked": "robots 차단 (자소설닷컴)",
        "public_fail": "ALIO 실패",
        "platform_fail": "플랫폼 실패",
        "company_fail": "기업 직접 실패",
        "worknet_fail": "워크넷 실패",
        "jasoseol_fail": "자소설닷컴 실패",
        "없음": "대기",
    }
    return labels.get(status, status or "대기")


def render_log_row(row: dict[str, Any]) -> str:
    return f"""<tr>
  <td>{escape(row.get("crawled_at"))}</td>
  <td>{status_badge(str(row.get("status") or ""))}</td>
  <td>{escape(row.get("new_jobs_count"))}</td>
  <td>{escape(row.get("duration_ms") or "")}</td>
  <td>{escape(row.get("error_message") or "")}</td>
</tr>"""


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def write_dashboard(
    path: str | Path,
    summary: dict[str, Any],
    jobs: list[Any],
    logs: list[Any],
    source_health: list[Any] | None = None,
    *,
    next_run_kst: str = "",
    auto_refresh: bool = False,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_dashboard(
            summary,
            jobs,
            logs,
            source_health,
            next_run_kst=next_run_kst,
            auto_refresh=auto_refresh,
        ),
        encoding="utf-8",
    )
