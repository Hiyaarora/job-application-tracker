"""Gemini wrapper: classify emails, draft replies, suggest a daily task.

Called sparingly — only after the Python pre-filter — to respect the free quota.
All model access goes through _model()/_generate() so tests can patch them.
"""
import json
import re
import time

import google.generativeai as genai

from . import config

# Map the email intent (decided by the LLM) to a tracker status. Status changes
# are derived here in Python so we never trust the model to invent a status.
INTENT_STATUS = {
    "confirmation": "In Review",
    "rejection": "Rejected",
    "interview_invite": "Interview Scheduled",
    "offer": "Offer",
    "recruiter_followup": None,   # may need a reply, but no status change
    "other": None,
}


def _model():
    """Return a configured Gemini model, or raise a friendly error if no key."""
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env "
            "(get one free at https://aistudio.google.com/apikey)."
        )
    genai.configure(api_key=config.GEMINI_API_KEY)
    return genai.GenerativeModel(config.GEMINI_MODEL)


def _is_quota_error(exc: Exception) -> bool:
    """True for rate-limit / quota (HTTP 429) errors from the Gemini API."""
    text = str(exc).lower()
    return "429" in text or "quota" in text or "resourceexhausted" in text


def _call_with_retry(fn, *, max_retries: int = 2, sleep_fn=time.sleep,
                     base_delay: float = 45.0):
    """Call fn(); on a quota/rate error wait and retry.

    Tuned for the free tier (~5 req/min): one ~45s wait clears the per-minute
    limit. We cap retries low so an exhausted *daily* quota fails fast instead
    of stalling an unattended daily run for minutes.
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if not _is_quota_error(exc) or attempt == max_retries:
                raise
            sleep_fn(base_delay)


def _generate(prompt: str) -> str:
    """Send a prompt to Gemini and return the raw text, retrying on rate limits."""
    return _call_with_retry(lambda: _model().generate_content(prompt).text)


def _extract_json(text: str) -> dict:
    """Parse a JSON object out of a model response, tolerating ```code fences```."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object found")
    return json.loads(match.group(0))


def classify_email(email: dict, candidates: list[tuple[str, str]]) -> dict:
    """Decide which tracked application an email relates to, and its intent.

    `candidates` is a list of (company, role) the user is tracking. Returns
    {matched_company, matched_role, intent, new_status, confidence}. On any
    parsing/model issue it returns a safe 'other' result with confidence 0.
    """
    listing = "\n".join(f"- {c} / {r}" for c, r in candidates) or "(none)"
    prompt = (
        "You classify job-search emails. Given the tracked applications and one "
        "email, decide which application it relates to (or none) and the intent.\n\n"
        f"Tracked applications:\n{listing}\n\n"
        f"Email sender: {email.get('sender', '')}\n"
        f"Subject: {email.get('subject', '')}\n"
        f"Body:\n{email.get('body', '')[:2000]}\n\n"
        "Respond with ONLY a JSON object with keys: "
        "matched_company (string or null), matched_role (string or null), "
        "intent (one of: confirmation, rejection, interview_invite, offer, "
        "recruiter_followup, other), confidence (0.0-1.0)."
    )
    try:
        data = _extract_json(_generate(prompt))
        intent = data.get("intent", "other")
        if intent not in INTENT_STATUS:
            intent = "other"
        return {
            "matched_company": data.get("matched_company"),
            "matched_role": data.get("matched_role"),
            "intent": intent,
            "new_status": INTENT_STATUS[intent],
            "confidence": float(data.get("confidence", 0.0)),
        }
    except (ValueError, json.JSONDecodeError, TypeError):
        return {
            "matched_company": None, "matched_role": None,
            "intent": "other", "new_status": None, "confidence": 0.0,
        }


def extract_application(email: dict) -> dict:
    """Detect whether an email is about a job the user applied to, and extract it.

    Returns {is_job_application, company, role, status, confidence}. Status is
    validated against config.STATUSES (defaults to 'Applied'). Safe defaults on
    any parsing/model error.
    """
    prompt = (
        "You read a single email and decide if it concerns a job the RECIPIENT "
        "applied to (application confirmation, recruiter outreach about a role "
        "they applied for, interview, rejection, or offer). Ignore generic job "
        "alerts, newsletters, and marketing.\n\n"
        f"Sender: {email.get('sender', '')}\n"
        f"Subject: {email.get('subject', '')}\n"
        f"Body:\n{email.get('body', '')[:2000]}\n\n"
        "Respond with ONLY a JSON object: is_job_application (bool), "
        "company (string or null), role (string or null), "
        "status (one of: Applied, In Review, Interview Scheduled, Rejected, Offer), "
        "confidence (0.0-1.0)."
    )
    try:
        data = _extract_json(_generate(prompt))
        status = data.get("status")
        if status not in config.STATUSES:
            status = "Applied"
        return {
            "is_job_application": bool(data.get("is_job_application", False)),
            "company": data.get("company"),
            "role": data.get("role"),
            "status": status,
            "confidence": float(data.get("confidence", 0.0)),
        }
    except (ValueError, json.JSONDecodeError, TypeError):
        return {
            "is_job_application": False, "company": None, "role": None,
            "status": "Applied", "confidence": 0.0,
        }


def propose_reply(email: dict) -> dict:
    """In ONE call, decide if an email needs a personal reply and draft it.

    Combining the decision and the draft keeps it to a single Gemini request per
    email. Returns {needs_reply: bool, draft: str}; safe defaults on any error.
    """
    prompt = (
        "You triage a job-search email. Decide if it needs a PERSONAL reply from "
        "the applicant — e.g. an interview invite to confirm/schedule, or a "
        "recruiter question. Rejections, automated confirmations, and newsletters "
        "do NOT need a reply.\n"
        "If it does, draft a concise, warm, professional reply under 150 words.\n\n"
        f"From: {email.get('sender', '')}\n"
        f"Subject: {email.get('subject', '')}\n"
        f"Body:\n{email.get('body', '')[:2000]}\n\n"
        'Respond with ONLY JSON: {"needs_reply": bool, "draft": string}. '
        'If no reply is needed, draft must be "".'
    )
    try:
        data = _extract_json(_generate(prompt))
        return {
            "needs_reply": bool(data.get("needs_reply", False)),
            "draft": (data.get("draft") or "").strip(),
        }
    except (ValueError, json.JSONDecodeError, TypeError):
        return {"needs_reply": False, "draft": ""}


def daily_task() -> str:
    """Suggest one skill-learning task for AI/ML testing roles."""
    prompt = (
        "Suggest ONE concrete, ~30-minute learning task for someone transitioning "
        "from QA into AI/ML testing roles. One or two sentences, actionable."
    )
    return _generate(prompt).strip()
