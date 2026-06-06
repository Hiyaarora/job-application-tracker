"""Orchestration layer. Coordinates Tracker + Gmail + LLM; holds no API details.

Everything is injectable (classifier, log_fn, emails) so the logic is testable
without network or quota.
"""
import json
from datetime import datetime, timedelta, timezone

from . import config


def load_seen(path=None) -> set:
    """Load a set of already-processed email ids (empty if none yet)."""
    path = path or config.SEEN_FILE
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()))
    except (ValueError, OSError):
        return set()


def save_seen(seen: set, path=None) -> None:
    """Persist a set of processed email ids."""
    path = path or config.SEEN_FILE
    config.ensure_app_dir()
    path.write_text(json.dumps(sorted(seen)))


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
        edate = email.get("date") or ""
        key = company.lower()
        if key not in merged:
            merged[key] = {"company": company, "role": role, "status": status, "date": edate}
        else:
            m = merged[key]
            if m["role"] == "(unknown)" and role != "(unknown)":
                m["role"] = role
            if _advances(status, m["status"]):
                m["status"] = status
            # Date Applied = the EARLIEST email from this company (the application),
            # not the latest (e.g. a rejection) or today's discovery date.
            if edate and (not m["date"] or edate < m["date"]):
                m["date"] = edate

    added, updated = [], []
    for m in merged.values():
        company, role, status = m["company"], m["role"], m["status"]
        existing = tracker.find_by_company(company)  # one row per company
        if existing is None:
            tracker.add_application(company, role, source="Email",
                                    date_applied=(m["date"] or None))
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


def propose_drafts(emails, proposer, seen: set | None = None, max_llm: int = 10) -> dict:
    """Find emails needing a reply and draft them — one LLM call per email.

    Skips noise (OTP/verification) and already-considered emails, caps LLM calls
    at `max_llm`, and records every email it considers in `seen` so a reply is
    never drafted twice. Returns {drafts: [{email, draft}], error}.
    """
    if seen is None:
        seen = set()
    candidates = [e for e in emails
                  if not _is_noise(e) and e.get("id") not in seen][:max_llm]

    drafts, error = [], None
    for email in candidates:
        try:
            r = proposer(email)
        except Exception as exc:  # quota/rate/network — stop, keep what we have
            error = str(exc)
            break
        seen.add(email.get("id"))
        if r.get("needs_reply") and r.get("draft"):
            drafts.append({"email": email, "draft": r["draft"]})
    return {"drafts": drafts, "error": error}


def review_draft(draft: str, prompt_fn, edit_fn):
    """Approve / edit / skip a draft. Returns the text to send, or None to skip."""
    choice = prompt_fn("[a]pprove & send / [e]dit / [s]kip? ").strip().lower()
    if choice == "a":
        return draft
    if choice == "e":
        return edit_fn(draft)
    return None


def weekly_summary(tracker, now=None) -> dict:
    """Compute growth metrics from the tracker (no LLM). `now` is injectable."""
    now = now or datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).date().isoformat()
    apps = tracker.get_applications()
    total = len(apps)

    responded = [a for a in apps if a.status != "Applied"]
    by_status = {s: sum(1 for a in apps if a.status == s) for s in config.STATUSES}

    return {
        "total": total,
        "by_status": by_status,
        "responses": len(responded),
        "response_rate": round(len(responded) / total, 2) if total else 0.0,
        "interviews": by_status["Interview Scheduled"],
        "offers": by_status["Offer"],
        "rejections": by_status["Rejected"],
        "pending": by_status["Applied"] + by_status["In Review"],
        "applied_this_week": sum(1 for a in apps if a.date_applied >= week_ago),
    }


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
