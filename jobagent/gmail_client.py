"""Thin Gmail API wrapper: list recent mail, parse it, and send replies.

Everything here returns plain dicts/strings so the agent layer never has to know
about the raw Gmail message format.
"""
import base64
import re
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


def _extract_plain(payload: dict) -> str:
    """Walk the MIME tree and return the first text/plain body found."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return _decode(data)
    for part in payload.get("parts", []) or []:
        text = _extract_plain(part)
        if text:
            return text
    # Fallback: a body at the root with no explicit text/plain mimeType.
    data = payload.get("body", {}).get("data")
    return _decode(data) if data else ""


def _domain(sender: str) -> str:
    """Pull the domain out of a 'Name <user@domain>' or 'user@domain' string."""
    m = re.search(r"[\w.+-]+@([\w.-]+)", sender)
    return m.group(1).lower() if m else ""


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
