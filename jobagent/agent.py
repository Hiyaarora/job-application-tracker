"""Orchestration layer. Coordinates Tracker + Gmail + LLM; holds no API details.

Everything is injectable (classifier, log_fn, emails) so the logic is testable
without network or quota.
"""
import json
from datetime import datetime, timezone

from . import config


def load_seen() -> set:
    """Load the set of already-scanned email ids (empty if none yet)."""
    if not config.SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(config.SEEN_FILE.read_text()))
    except (ValueError, OSError):
        return set()


def save_seen(seen: set) -> None:
    """Persist the set of scanned email ids."""
    config.ensure_app_dir()
    config.SEEN_FILE.write_text(json.dumps(sorted(seen)))


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


# Cheap signals that an email might be about a job application. Used to narrow
# the inbox BEFORE spending any LLM call during discovery.
_JOB_KEYWORDS = (
    "application", "applied", "applying", "candidate", "candidacy", "interview",
    "recruiter", "recruiting", "talent", "position", "role", "hiring", "job",
    "we received your", "thank you for your interest", "next steps", "assessment",
)

# Status precedence — higher index = more advanced. Used to dedup and to decide
# whether a discovered status should overwrite an existing one.
_RANK = {s: i for i, s in enumerate(config.STATUSES)}


def _is_job_candidate(email: dict) -> bool:
    haystack = " ".join([
        email.get("subject", ""), email.get("snippet", ""), email.get("body", ""),
    ]).lower()
    return any(kw in haystack for kw in _JOB_KEYWORDS)


def discover_applications(tracker, emails, extractor, min_confidence: float = 0.6,
                          max_llm: int = 15, log_fn=None, seen: set | None = None) -> dict:
    """Scan emails, extract job applications, and populate the tracker.

    Keyword-filters first (no LLM), skips emails already in `seen`, caps LLM
    calls at `max_llm`, dedups by company+role keeping the most-advanced status,
    then adds new applications and bumps existing ones. Successfully scanned
    email ids are added to `seen` so later runs work through the backlog.
    Returns {added, updated, skipped_quota, error}.
    """
    if log_fn is None:
        log_fn = _log_change
    if seen is None:
        seen = set()

    candidates = [e for e in emails
                  if _is_job_candidate(e) and e.get("id") not in seen]
    to_scan = candidates[:max_llm]
    skipped_quota = len(candidates) - len(to_scan)

    # Collapse multiple emails for the same application to its furthest status.
    discovered: dict[tuple[str, str], dict] = {}
    error = None
    for email in to_scan:
        try:
            r = extractor(email)
        except Exception as exc:  # quota/rate/network — stop hammering, keep work so far
            error = str(exc)
            break
        seen.add(email.get("id"))  # mark only after a successful scan
        if not r.get("is_job_application") or r.get("confidence", 0.0) < min_confidence:
            continue
        company, role = r.get("company"), r.get("role")
        if not company:
            continue
        role = role or "(unknown)"
        status = r.get("status", "Applied")
        key = (company.lower(), role.lower())
        if key not in discovered or _RANK.get(status, 0) > _RANK.get(discovered[key]["status"], 0):
            discovered[key] = {"company": company, "role": role, "status": status}

    added, updated = [], []
    for info in discovered.values():
        company, role, status = info["company"], info["role"], info["status"]
        existing = tracker.find_application(company, role)
        if existing is None:
            tracker.add_application(company, role, source="Email")
            if status != "Applied":
                tracker.update_status(company, role, status, note="discovered from email")
            added.append(f"{company} / {role} [{status}]")
            log_fn(f"discovered {company} / {role} -> {status}")
        elif _RANK.get(status, 0) > _RANK.get(existing.status, 0):
            tracker.update_status(company, role, status, note="discovered from email")
            updated.append(f"{company} / {role}: {existing.status} -> {status}")
            log_fn(f"discovered update {company} / {role} -> {status}")

    return {"added": added, "updated": updated,
            "skipped_quota": skipped_quota, "error": error}


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
        try:
            result = classifier(email, candidates)
        except Exception:  # quota/rate/network — stop, keep changes already made
            break
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
