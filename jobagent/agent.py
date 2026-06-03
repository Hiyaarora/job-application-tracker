"""Orchestration layer. Coordinates Tracker + Gmail + LLM; holds no API details.

Everything is injectable (classifier, log_fn, emails) so the logic is testable
without network or quota.
"""
from datetime import datetime, timezone

from . import config


def _prefilter(emails: list[dict], apps) -> list[dict]:
    """Keep only emails that mention a tracked company — BEFORE any LLM call.

    This is the quota guard: cheap Python string matching narrows hundreds of
    emails down to the few worth spending a Gemini call on.
    """
    tokens = {a.company.lower() for a in apps if a.company}
    kept = []
    for e in emails:
        haystack = " ".join([
            e.get("sender", ""), e.get("sender_domain", ""),
            e.get("subject", ""), e.get("snippet", ""), e.get("body", ""),
        ]).lower()
        if any(tok and tok in haystack for tok in tokens):
            kept.append(e)
    return kept


def _log_change(message: str) -> None:
    """Append a timestamped line to the changes log."""
    config.ensure_app_dir()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(config.CHANGES_LOG, "a") as fh:
        fh.write(f"{stamp}  {message}\n")


def sync_inbox(tracker, emails, classifier, min_confidence: float = 0.6,
               log_fn=_log_change) -> list[str]:
    """Pre-filter emails, classify the survivors, and update matching statuses.

    Returns a list of human-readable change descriptions (also logged).
    """
    apps = tracker.get_applications()
    candidates = [(a.company, a.role) for a in apps]
    changes: list[str] = []

    for email in _prefilter(emails, apps):
        result = classifier(email, candidates)
        new_status = result.get("new_status")
        company = result.get("matched_company")
        role = result.get("matched_role")

        if not (new_status and company and role):
            continue
        if result.get("confidence", 0.0) < min_confidence:
            continue

        existing = tracker.find_application(company, role)
        if existing is None or existing.status == new_status:
            continue

        note = f"auto: {result.get('intent')} from {email.get('sender', '')}"
        tracker.update_status(company, role, new_status, note=note)
        msg = f"{company} / {role}: {existing.status} -> {new_status} ({result.get('intent')})"
        changes.append(msg)
        log_fn(msg)

    return changes
