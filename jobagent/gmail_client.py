"""Thin Gmail API wrapper: list recent mail, parse it, and send replies.

Everything here returns plain dicts/strings so the agent layer never has to know
about the raw Gmail message format.
"""
import base64
import html as _html
import re
from datetime import datetime, timezone
from email.mime.text import MIMEText

# Let the Google client retry transient network/5xx errors with backoff.
_RETRIES = 3


def list_recent(service, days: int = 2, max_results: int = 100,
                query: str | None = None) -> list[dict]:
    """Return [{id, threadId}, ...] for messages from the last `days` days.

    Pass `query` to AND an extra Gmail search expression (e.g. an application
    filter) onto the date window, so Gmail narrows results before we fetch them.
    """
    q = f"newer_than:{days}d"
    if query:
        q += f" ({query})"
    resp = (service.users().messages()
            .list(userId="me", q=q, maxResults=max_results)
            .execute(num_retries=_RETRIES))
    return resp.get("messages", [])


def get_message(service, msg_id: str) -> dict:
    """Fetch the full message resource for a message id."""
    return (service.users().messages()
            .get(userId="me", id=msg_id, format="full")
            .execute(num_retries=_RETRIES))


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    """Strip HTML to readable text so the AI reads content, not markup."""
    html = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)          # drop all tags
    html = _html.unescape(html)                        # &amp; -> & etc.
    return re.sub(r"\s+", " ", html).strip()


def _find_part(payload: dict, mime: str) -> str:
    """Return the decoded body of the first part with the given mime type."""
    if payload.get("mimeType") == mime:
        data = payload.get("body", {}).get("data")
        if data:
            return _decode(data)
    for part in payload.get("parts", []) or []:
        found = _find_part(part, mime)
        if found:
            return found
    return ""


def _extract_plain(payload: dict) -> str:
    """Best readable text for an email: prefer text/plain, else convert HTML."""
    plain = _find_part(payload, "text/plain")
    if plain:
        return plain
    html = _find_part(payload, "text/html")
    if html:
        return _html_to_text(html)
    # Fallback: a body at the root with no explicit part mimeType.
    data = payload.get("body", {}).get("data")
    if not data:
        return ""
    raw = _decode(data)
    return _html_to_text(raw) if "<" in raw and ">" in raw else raw


def sender_email(sender: str) -> str:
    """Extract the bare email address from a 'Name <addr>' or 'addr' string."""
    m = re.search(r"[\w.+-]+@[\w.-]+", sender)
    return m.group(0) if m else ""


def _domain(sender: str) -> str:
    """Pull the domain out of a 'Name <user@domain>' or 'user@domain' string."""
    m = re.search(r"[\w.+-]+@([\w.-]+)", sender)
    return m.group(1).lower() if m else ""


def _date_from_internal(internal_ms: str) -> str:
    """Gmail internalDate (epoch ms string) -> ISO date 'YYYY-MM-DD' (UTC)."""
    try:
        ts = int(internal_ms) / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse_message(msg: dict) -> dict:
    """Flatten a Gmail message into the fields the agent needs."""
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])
    sender = _header(headers, "From")
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "sender": sender,
        "sender_domain": _domain(sender),
        "subject": _header(headers, "Subject"),
        "snippet": msg.get("snippet", ""),
        "body": _extract_plain(payload),
        "date": _date_from_internal(msg.get("internalDate")),
    }


def send_message(service, to: str, subject: str, body: str, thread_id: str | None = None) -> dict:
    """Send a plain-text email. Pass thread_id to keep it in the same conversation."""
    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    message = {"raw": raw}
    if thread_id:
        message["threadId"] = thread_id
    return (service.users().messages()
            .send(userId="me", body=message)
            .execute(num_retries=_RETRIES))
