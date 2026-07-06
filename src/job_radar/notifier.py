from __future__ import annotations

import urllib.parse
import urllib.request


def build_message(job: dict[str, object]) -> str:
    title = str(job.get("title", "제목 미확인 공고"))
    company = str(job.get("company_name", "미확인 기관"))
    score = job.get("score", 0)
    deadline = str(job.get("deadline", "") or "미확인")
    alio_detail_url = str(job.get("alio_detail_url", "") or "")
    external_url = str(job.get("external_url", "") or "")
    fallback_url = str(job.get("url", "") or "")
    matched = ", ".join(str(item) for item in job.get("matched_keywords", []) or [])
    lines = [
        "[새 공공기관 채용공고]",
        f"기관: {company}",
        f"공고: {title}",
        f"마감: {deadline}",
        f"점수: {score}",
    ]
    if matched:
        lines.append(f"매칭: {matched}")
    if alio_detail_url:
        lines.append(f"ALIO 상세: {alio_detail_url}")
    if external_url and external_url != alio_detail_url:
        lines.append(f"외부 원문: {external_url}")
    elif not alio_detail_url and fallback_url:
        lines.append(f"링크: {fallback_url}")
    return "\n".join(lines)


def send_telegram(*, bot_token: str, chat_id: str, text: str) -> None:
    if not bot_token or not chat_id:
        raise ValueError("Telegram token/chat_id is not configured")
    endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(endpoint, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()
