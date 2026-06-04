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


# High-signal phrases that an email is about a real application (not a job
# alert/newsletter). Deliberately avoids common words like "role"/"job" that
# match everything. Used as a fallback filter; `discover` normally relies on a
# precise Gmail search instead (config.APPLICATION_QUERY).
_JOB_KEYWORDS = (
    "application", "applied", "applying", "candidacy", "interview", "recruiter",
    "we received your", "thank you for your interest", "thank you for applying",
    "your application", "next steps", "assessment", "submission",
)

# Status funnel order — higher rank = further along. Status only ever moves
# forward (Applied -> In Review -> Interview -> Rejected/Offer), driven by the
# most-advanced email from a company. Unknown status ranks below everything.
STATUS_RANK = {s: i for i, s in enumerate(config.STATUSES)}


def _rank(status: str) -> int:
    return STATUS_RANK.get(status, -1)


def _advances(new_status: str, current_status: str) -> bool:
    """True if new_status is further along the funnel than current_status."""
    return _rank(new_status) > _rank(current_status)


def _is_job_candidate(email: dict) -> bool:
    haystack = " ".join([
        email.get("subject", ""), email.get("snippet", ""), email.get("body", ""),
    ]).lower()
    return any(kw in haystack for kw in _JOB_KEYWORDS)


# Verification / OTP / login mails: cost an LLM call but carry no status. Skip
# them cheaply so we never waste a Gemini request on them.
_NOISE_PATTERNS = (
    "verification code", "one-time", "otp", "confirm your email",
    "verify your email", "security code", "sign-in code", "login code",
    "log in code", "2-step", "two-factor",
)


def _is_noise(email: dict) -> bool:
    hay = (email.get("subject", "") + " " + email.get("snippet", "")).lower()
    return any(p in hay for p in _NOISE_PATTERNS)


def discover_applications(tracker, emails, extractor, min_confidence: float = 0.6,
                          max_llm: int = 15, log_fn=None, seen: set | None = None,
                          apply_keyword_filter: bool = True) -> dict:
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
                  if (not apply_keyword_filter or _is_job_candidate(e))
                  and not _is_noise(e)
                  and e.get("id") not in seen]
    to_scan = candidates[:max_llm]
    skipped_quota = len(candidates) - len(to_scan)

    # Merge ALL scanned emails per COMPANY: keep a real role (over "(unknown)")
    # and the most-advanced status. This collapses a company's many emails
    # (OTP, confirmation, rejection, ...) into one application.
    merged: dict[str, dict] = {}
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
        company = r.get("company")
        if not company:
            continue
        role = r.get("role") or "(unknown)"
        status = r.get("status", "Applied")
        key = company.lower()
        if key not in merged:
            merged[key] = {"company": company, "role": role, "status": status}
        else:
            m = merged[key]
            if m["role"] == "(unknown)" and role != "(unknown)":
                m["role"] = role
            if _advances(status, m["status"]):
                m["status"] = status

    added, updated = [], []
    for m in merged.values():
        company, role, status = m["company"], m["role"], m["status"]
        existing = tracker.find_by_company(company)  # one row per company
        if existing is None:
            tracker.add_application(company, role, source="Email")
            if _advances(status, "Applied"):
                tracker.update_status(company, role, status, note="discovered from email")
            added.append(f"{company} / {role} [{status}]")
            log_fn(f"discovered {company} / {role} -> {status}")
        elif _advances(status, existing.status):
            tracker.update_status(existing.company, existing.role, status,
                                  note="discovered from email")
            updated.append(f"{company} / {existing.role}: {existing.status} -> {status}")
            log_fn(f"discovered update {company} -> {status}")

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

        if not (new_status and company):
            continue
        if result.get("confidence", 0.0) < min_confidence:
            continue

        # Match by company, and only ever move the status FORWARD in the funnel.
        existing = tracker.find_by_company(company)
        if existing is None or not _advances(new_status, existing.status):
            continue

        note = f"auto: {result.get('intent')} from {email.get('sender', '')}"
        tracker.update_status(existing.company, existing.role, new_status, note=note)
        msg = f"{company} / {existing.role}: {existing.status} -> {new_status} ({result.get('intent')})"
        changes.append(msg)
        log_fn(msg)

    return changes
