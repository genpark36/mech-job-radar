from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .db import dedupe_group_key


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
    log_rows = "\n".join(render_log_row(dict(row)) for row in logs)
    source_rows = "\n".join(render_source_row(dict(row)) for row in (source_health or []))
    last_log = summary.get("last_log") or {}
    job_payload = json.dumps(
        [serialize_job(row) for row in job_dicts],
        ensure_ascii=False,
    )
    fit_levels = sorted({classify_mechanical_fit(row)["level"] for row in job_dicts})
    sources = sorted({source_label(row.get("source_platform")) for row in job_dicts if row.get("source_platform")})
    sectors = sorted({classify_sector(row) for row in job_dicts})
    watch_grades = sorted(
        {
            watch_info(row).get("watchGrade")
            for row in job_dicts
            if watch_info(row).get("watchGrade")
        }
    )
    recommended_count = sum(
        1 for row in job_dicts if classify_mechanical_fit(row)["level"] in ("기계 추천", "검토 필요")
    )
    source_options = "\n".join(f'<option value="{escape(source)}">{escape(source)}</option>' for source in sources)
    sector_options = "\n".join(f'<option value="{escape(sector)}">{escape(sector)}</option>' for sector in sectors)
    fit_options = "\n".join(f'<option value="{escape(level)}">{escape(level)}</option>' for level in fit_levels)
    watch_options = "\n".join(
        f'<option value="{escape(grade)}">관심기업 {escape(grade)}</option>'
        for grade in watch_grades
    )
    last_status = str(last_log.get("status", "없음") or "없음")
    last_status_html = status_badge(last_status)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>채용 공고</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f8fb;
      color: #172033;
    }}
    header {{
      background: #0f2d52;
      color: white;
      padding: 24px 32px;
    }}
    main {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 24px;
    }}
    .stats, .filters {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .filters {{
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }}
    .stat, section {{
      background: white;
      border: 1px solid #dce3ee;
      border-radius: 8px;
      padding: 16px;
    }}
    .stat strong {{
      display: block;
      font-size: 28px;
      margin-top: 4px;
    }}
    .stat .status-pill {{
      margin-top: 10px;
    }}
    h1, h2 {{
      margin: 0;
    }}
    h2 {{
      margin-bottom: 12px;
      font-size: 18px;
    }}
    input, select, button {{
      width: 100%;
      min-height: 38px;
      box-sizing: border-box;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: white;
      color: #172033;
      font: inherit;
      padding: 8px 10px;
    }}
    button {{
      cursor: pointer;
      background: #0f2d52;
      color: white;
      border-color: #0f2d52;
      font-weight: 700;
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      min-width: 1180px;
    }}
    th, td {{
      border-bottom: 1px solid #e7edf5;
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: #53627a;
      font-weight: 600;
      white-space: nowrap;
    }}
    a {{
      color: #0b63ce;
    }}
    .links {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .button-link {{
      display: inline-block;
      padding: 5px 8px;
      border: 1px solid #b8c7db;
      border-radius: 6px;
      background: #f8fbff;
      color: #0b4f9c;
      font-size: 12px;
      font-weight: 600;
      text-decoration: none;
      white-space: nowrap;
    }}
    .button-link.secondary {{
      background: white;
      color: #53627a;
    }}
    .muted {{
      color: #6c7890;
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 26px;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .status-pill::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: currentColor;
    }}
    .status-ok {{
      background: #e7f7ef;
      color: #087a4a;
    }}
    .status-warn {{
      background: #fff3d7;
      color: #a15c00;
    }}
    .status-error {{
      background: #fde8e8;
      color: #c21f32;
    }}
    .status-idle {{
      background: #edf2f7;
      color: #53627a;
    }}
    .sector {{
      display: inline-flex;
      align-items: center;
      padding: 2px 7px;
      border-radius: 999px;
      background: #edf4ff;
      color: #174b8f;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .watch {{
      display: inline-flex;
      align-items: center;
      padding: 2px 7px;
      border-radius: 999px;
      background: #eef2ff;
      color: #3730a3;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .fit {{
      display: inline-flex;
      align-items: center;
      padding: 2px 7px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .fit-strong {{
      background: #e7f7ef;
      color: #087a4a;
    }}
    .fit-review {{
      background: #fff3d7;
      color: #9a5b00;
    }}
    .fit-low {{
      background: #edf2f7;
      color: #53627a;
    }}
    .fit-reject {{
      background: #fde8e8;
      color: #b42335;
    }}
    .score {{
      font-weight: 700;
      color: #0f6b4f;
    }}
    .toolbar {{
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      margin: 0 0 12px;
      flex-wrap: wrap;
    }}
    .toolbar p {{
      margin: 0;
    }}
    .check-group {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      min-height: 38px;
      padding: 8px 10px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: white;
    }}
    .check-group label {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 13px;
      white-space: nowrap;
    }}
    .check-group input {{
      width: auto;
      min-height: auto;
      padding: 0;
    }}
    .url-cell {{
      max-width: 520px;
      overflow-wrap: anywhere;
    }}
  </style>
</head>
<body>
  <header>
    <h1>채용 공고</h1>
    <p>기계/생산기술/설비/공정/품질 공고 전체 모니터</p>
  </header>
  <main>
    <div class="stats">
      <div class="stat">전체 감지 공고<strong>{summary["job_count"]}</strong></div>
      <div class="stat">현재 표시<strong id="visibleCount">{len(job_dicts)}</strong></div>
      <div class="stat">기계 후보<strong>{recommended_count}</strong></div>
      <div class="stat">크롤링 로그<strong>{summary["log_count"]}</strong></div>
      <div class="stat">최근 상태<br>{last_status_html}</div>
      <div class="stat">다음 자동 갱신<strong>{escape(next_run_kst or "서버 실행 시 표시")}</strong></div>
    </div>
    <section>
      <div class="toolbar">
        <h2>전체 공고</h2>
        <p class="muted">브라우저에서 즉시 필터링합니다. 기본은 전체 표시입니다.</p>
      </div>
      <div class="filters">
        <input id="q" placeholder="기업/제목/지역/키워드 검색">
        <select id="searchMode">
          <option value="and">검색어 AND</option>
          <option value="or">검색어 OR</option>
        </select>
        <select id="source">
          <option value="">전체 출처</option>
          {source_options}
        </select>
        <select id="sector">
          <option value="">전체 구분</option>
          {sector_options}
        </select>
        <select id="fit">
          <option value="">전체 적합도</option>
          {fit_options}
        </select>
        <select id="watchGrade">
          <option value="">전체 관심기업</option>
          {watch_options}
        </select>
        <div class="check-group" aria-label="경력 필터">
          <label><input type="checkbox" name="career" value="신입">신입</label>
          <label><input type="checkbox" name="career" value="경력">경력</label>
          <label><input type="checkbox" name="career" value="인턴">인턴</label>
          <label><input type="checkbox" name="career" value="경력무관">무관</label>
        </div>
        <select id="careerMode">
          <option value="or">경력 OR</option>
          <option value="and">경력 AND</option>
        </select>
        <select id="minScore">
          <option value="-999">전체 점수</option>
          <option value="0">0점 이상</option>
          <option value="1">1점 이상</option>
          <option value="5">5점 이상</option>
          <option value="8">8점 이상</option>
          <option value="12">12점 이상</option>
        </select>
        <select id="sortField">
          <option value="detected_at">감지일</option>
          <option value="deadline">마감일</option>
          <option value="score">점수</option>
          <option value="company_name">기관</option>
          <option value="title">제목</option>
          <option value="source_label">출처</option>
          <option value="career_type">경력</option>
        </select>
        <select id="sortDir">
          <option value="desc">내림차순</option>
          <option value="asc">오름차순</option>
        </select>
        <button type="button" onclick="resetFilters()">초기화</button>
        {"<button type=\"button\" onclick=\"runCrawl()\">수동 갱신</button>" if auto_refresh else ""}
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>점수</th>
              <th>출처</th>
              <th>적합도</th>
              <th>구분</th>
              <th>관심기업</th>
              <th>기관</th>
              <th>제목</th>
              <th>마감</th>
              <th>경력</th>
              <th>고용</th>
              <th>지역</th>
              <th>분야</th>
              <th>근거</th>
              <th>링크</th>
            </tr>
          </thead>
          <tbody id="jobsBody"></tbody>
        </table>
      </div>
    </section>
    <section style="margin-top: 20px;">
      <div class="toolbar">
        <h2>수집 소스 상태</h2>
        <p class="muted">실패하거나 한동안 신규가 없는 소스를 확인합니다.</p>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>출처</th>
              <th>상태</th>
              <th>최근 실행</th>
              <th>신규</th>
              <th>오류횟수</th>
              <th>소요</th>
              <th>URL</th>
              <th>오류</th>
            </tr>
          </thead>
          <tbody>{source_rows or '<tr><td colspan="8" class="muted">아직 등록된 수집 소스가 없습니다.</td></tr>'}</tbody>
        </table>
      </div>
    </section>
    <section style="margin-top: 20px;">
      <h2>최근 로그</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>시간</th>
              <th>상태</th>
              <th>신규</th>
              <th>소요</th>
              <th>오류</th>
            </tr>
          </thead>
          <tbody>{log_rows or '<tr><td colspan="5" class="muted">아직 로그가 없습니다.</td></tr>'}</tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const JOBS = {job_payload};
    const body = document.getElementById("jobsBody");
    const controls = [
      "q", "searchMode", "source", "sector", "watchGrade", "careerMode",
      "fit", "minScore", "sortField", "sortDir"
    ].map((id) => document.getElementById(id));
    const careerChecks = [...document.querySelectorAll('input[name="career"]')];

    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }}[char]));
    }}

    function linkHtml(job) {{
      const links = [];
      if (job.alio_detail_url) {{
        links.push(`<a class="button-link" href="${{escapeHtml(job.alio_detail_url)}}" target="_blank" rel="noreferrer">ALIO 상세</a>`);
      }}
      if (job.external_url && job.external_url !== job.alio_detail_url) {{
        links.push(`<a class="button-link secondary" href="${{escapeHtml(job.external_url)}}" target="_blank" rel="noreferrer">원문</a>`);
      }}
      if (!links.length && job.url) {{
        links.push(`<a class="button-link secondary" href="${{escapeHtml(job.url)}}" target="_blank" rel="noreferrer">열기</a>`);
      }}
      return `<div class="links">${{links.join("")}}</div>`;
    }}

    function words(value) {{
      return value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    }}

    function queryMatches(haystack, query, mode) {{
      const terms = words(query);
      if (!terms.length) return true;
      return mode === "and"
        ? terms.every((term) => haystack.includes(term))
        : terms.some((term) => haystack.includes(term));
    }}

    function careerMatches(job, selected, mode) {{
      if (!selected.length) return true;
      const career = String(job.career_type || "");
      const normalized = career.replace(/\\s+/g, "");
      return mode === "and"
        ? selected.every((item) => normalized.includes(item))
        : selected.some((item) => normalized.includes(item));
    }}

    function compareJobs(a, b, field, dir) {{
      const av = a[field] ?? "";
      const bv = b[field] ?? "";
      let result = 0;
      if (field === "score") {{
        result = Number(av || 0) - Number(bv || 0);
      }} else {{
        result = String(av).localeCompare(String(bv), "ko", {{ numeric: true, sensitivity: "base" }});
      }}
      return dir === "asc" ? result : -result;
    }}

    function render() {{
      const q = document.getElementById("q").value.trim().toLowerCase();
      const searchMode = document.getElementById("searchMode").value;
      const source = document.getElementById("source").value;
      const sector = document.getElementById("sector").value;
      const fit = document.getElementById("fit").value;
      const selectedCareers = careerChecks.filter((check) => check.checked).map((check) => check.value);
      const careerMode = document.getElementById("careerMode").value;
      const minScore = Number(document.getElementById("minScore").value || -999);
      const sortField = document.getElementById("sortField").value;
      const sortDir = document.getElementById("sortDir").value;
      const rows = JOBS.filter((job) => {{
        const haystack = [
          job.company_name, job.title, job.deadline, job.career_type,
          job.employment_type, job.location, job.field, job.source_label, job.sector_label,
          job.fit_level, job.fit_reasons, job.matched_keywords, job.watch_label
        ].join(" ").toLowerCase();
        return queryMatches(haystack, q, searchMode)
          && (!source || job.source_label.split("·").includes(source))
          && (!sector || job.sector_label === sector)
          && (!document.getElementById("watchGrade").value || job.watch_grade === document.getElementById("watchGrade").value)
          && (!fit || job.fit_level === fit)
          && careerMatches(job, selectedCareers, careerMode)
          && (Number(job.score || 0) >= minScore);
      }}).sort((a, b) => compareJobs(a, b, sortField, sortDir));
      document.getElementById("visibleCount").textContent = rows.length;
      body.innerHTML = rows.map((job) => `
        <tr>
          <td class="score">${{escapeHtml(job.score)}}</td>
          <td>${{escapeHtml(job.source_label)}}</td>
          <td><span class="fit ${{escapeHtml(job.fit_class)}}">${{escapeHtml(job.fit_level)}}</span></td>
          <td><span class="sector">${{escapeHtml(job.sector_label)}}</span></td>
          <td>${{job.watch_label ? `<span class="watch">${{escapeHtml(job.watch_label)}}</span>` : ""}}</td>
          <td>${{escapeHtml(job.company_name || "회사명 미확인")}}</td>
          <td>${{escapeHtml(job.title)}}</td>
          <td>${{escapeHtml(job.deadline || "-")}}</td>
          <td>${{escapeHtml(job.career_type || "-")}}</td>
          <td>${{escapeHtml(job.employment_type || "-")}}</td>
          <td>${{escapeHtml(job.location || "-")}}</td>
          <td>${{escapeHtml(job.field || "-")}}</td>
          <td>${{escapeHtml(job.fit_reasons)}}</td>
          <td>${{linkHtml(job)}}</td>
        </tr>
      `).join("") || '<tr><td colspan="14" class="muted">조건에 맞는 공고가 없습니다.</td></tr>';
    }}

    function resetFilters() {{
      controls.forEach((control) => control.value = "");
      document.getElementById("searchMode").value = "and";
      document.getElementById("careerMode").value = "or";
      document.getElementById("minScore").value = "-999";
      document.getElementById("sortField").value = "detected_at";
      document.getElementById("sortDir").value = "desc";
      careerChecks.forEach((check) => check.checked = false);
      render();
    }}

    async function runCrawl() {{
      if (!confirm("지금 전체 수집을 실행할까요?")) return;
      const response = await fetch("/run-crawl", {{ method: "POST" }});
      const result = await response.json();
      alert(result.message || "수집 요청 완료");
      location.reload();
    }}

    controls.forEach((control) => control.addEventListener("input", render));
    careerChecks.forEach((control) => control.addEventListener("change", render));
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
        "watch_industry": watch.get("industry", ""),
        "company_name": row.get("company_name") or "",
        "title": row.get("title") or "",
        "deadline": row.get("deadline") or "",
        "career_type": row.get("career_type") or "",
        "employment_type": row.get("employment_type") or "",
        "location": row.get("location") or "",
        "field": row.get("field") or "",
        "matched_keywords": row.get("matched_keywords") or "",
        "detected_at": row.get("detected_at") or "",
        "url": row.get("url") or "",
        "alio_detail_url": row.get("alio_detail_url") or "",
        "external_url": row.get("external_url") or "",
    }


def watch_info(row: dict[str, Any]) -> dict[str, str]:
    raw_data = row.get("raw_data")
    if not raw_data:
        return {}
    if isinstance(raw_data, str):
        try:
            parsed = json.loads(raw_data)
        except json.JSONDecodeError:
            return {}
    elif isinstance(raw_data, dict):
        parsed = raw_data
    else:
        return {}
    watch = parsed.get("companyWatchlist")
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


def classify_mechanical_fit(row: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        str(row.get(key) or "")
        for key in (
            "company_name",
            "title",
            "field",
            "employment_type",
            "career_type",
            "location",
            "matched_keywords",
        )
    ).lower()
    score = int(row.get("score") or 0)
    strong_terms = (
        "기계",
        "기계직",
        "기계설비",
        "설비",
        "설비보전",
        "보전",
        "정비",
        "유지보수",
        "공장공무",
        "시설공무",
        "설비공무",
        "공무팀",
        "생산기술",
        "공정기술",
        "설비기술",
        "제조기술",
        "제조",
        "기술직",
        "플랜트",
        "철도차량",
        "자동차",
        "모빌리티",
        "반도체",
        "방산",
        "화약",
        "발전설비",
        "유틸리티",
        "utility",
        "maintenance",
        "공조",
        "냉동",
        "보일러",
    )
    review_terms = (
        "품질",
        "품질관리",
        "안전",
        "안전관리",
        "환경",
        "에너지",
        "연구직",
        "연구원",
        "연구개발",
        "기술개발",
        "제품개발",
        "r&d",
        "cad",
        "도면",
        "장비",
        "시설",
    )
    reject_terms = (
        "마케팅",
        "영업",
        "회계",
        "재무",
        "인사",
        "전산",
        "소프트웨어",
        "sw",
        "디자이너",
        "브랜드",
        "md",
        "교사",
        "강사",
        "상담",
        "간호",
        "요양",
        "조리",
    )
    strong_hits = [term for term in strong_terms if term in text]
    review_hits = [term for term in review_terms if term in text]
    reject_hits = [term for term in reject_terms if term in text]
    if strong_hits and score >= 8:
        return {
            "level": "기계 추천",
            "class": "fit-strong",
            "reasons": strong_hits[:5],
        }
    if strong_hits or review_hits:
        return {
            "level": "검토 필요",
            "class": "fit-review",
            "reasons": (strong_hits + review_hits)[:5],
        }
    if reject_hits:
        return {
            "level": "비추천",
            "class": "fit-reject",
            "reasons": reject_hits[:5],
        }
    return {
        "level": "낮은 관련",
        "class": "fit-low",
        "reasons": [],
    }


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
        "공단",
        "재단",
        "진흥원",
        "공단",
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
