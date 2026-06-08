"""Evaluation suite: score the agent's email extraction against a golden set.

Scoring functions are pure and unit-tested. LLM outputs are cached so eval runs
are free and deterministic; pass live=True to re-record via Gemini.
"""
import json
import re
from pathlib import Path

from . import agent, config

_COMPANY_SUFFIXES = ("inc", "ltd", "llc", "technologies", "pvt", "limited", "corp", "co")

# Default locations (project-root-relative).
EVALS_DIR = Path(__file__).resolve().parent.parent / "evals"
DATASET_PATH = EVALS_DIR / "dataset.jsonl"
CACHE_DIR = EVALS_DIR / "cache" / "extract"
REPORT_PATH = EVALS_DIR / "report.md"

THRESHOLDS = {"is_job_application": 0.90, "status": 0.80, "company": 0.85}


# --------------------------------------------------------------------------- #
# Scoring primitives (pure)
# --------------------------------------------------------------------------- #
def norm_company(name) -> str:
    """Lowercase, strip punctuation and common company suffixes."""
    if not name:
        return ""
    s = re.sub(r"[^\w\s]", " ", str(name).lower())
    tokens = [t for t in s.split() if t not in _COMPANY_SUFFIXES]
    return " ".join(tokens).strip()


def company_match(expected, actual) -> bool:
    e, a = norm_company(expected), norm_company(actual)
    if not e or not a:
        return e == a
    return e == a or e in a or a in e


def _norm_role(role) -> str:
    if not role:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(role).lower())).strip()


def role_match(expected, actual) -> bool:
    """Fuzzy: both empty -> match; else normalized containment either way."""
    e, a = _norm_role(expected), _norm_role(actual)
    if not e and not a:
        return True
    if not e or not a:
        return False
    return e == a or e in a or a in e


def status_match(expected, actual) -> bool:
    return (expected or "") == (actual or "")


# --------------------------------------------------------------------------- #
# Metrics (pure)
# --------------------------------------------------------------------------- #
def prf(expected: list, predicted: list) -> tuple:
    """Precision, recall, F1 for boolean classification."""
    tp = sum(1 for e, p in zip(expected, predicted) if e and p)
    fp = sum(1 for e, p in zip(expected, predicted) if p and not e)
    fn = sum(1 for e, p in zip(expected, predicted) if e and not p)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def confusion_matrix(expected: list, predicted: list, labels: list) -> dict:
    """Nested dict cm[expected_label][predicted_label] = count."""
    cm = {row: {col: 0 for col in labels} for row in labels}
    for e, p in zip(expected, predicted):
        if e in cm and p in cm[e]:
            cm[e][p] += 1
    return cm


# --------------------------------------------------------------------------- #
# Dataset + cache
# --------------------------------------------------------------------------- #
def load_dataset(path=DATASET_PATH) -> list:
    """Read a JSONL dataset, skipping blank/malformed lines (with a warning)."""
    cases = []
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"  ! skipping malformed dataset line {i}")
    return cases


def get_extraction(case: dict, live: bool, extractor=None):
    """Return extract_application output for a case, via cache.

    live=True  -> call `extractor` and record to cache.
    live=False -> read cache; return None if not recorded yet.
    `extractor` defaults to llm.extract_application (imported lazily).
    """
    cache_file = Path(CACHE_DIR) / f"{case['id']}.json"
    if not live:
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        return None
    if extractor is None:
        from . import llm
        extractor = llm.extract_application
    result = extractor(case["email"])
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, indent=2))
    return result


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def _score_filters(cases: list) -> dict:
    """Run deterministic filters against expected labels."""
    total = passed = 0
    noise_exp, noise_pred = [], []
    cand_exp, cand_pred = [], []
    for c in cases:
        f = c.get("filters")
        if not f:
            continue
        email = c["email"]
        is_noise = agent._is_noise(email)
        is_cand = agent._is_job_candidate(email)
        priority = agent._scan_priority(email)
        checks = [is_noise == f["is_noise"], is_cand == f["is_job_candidate"],
                  priority == f["priority"]]
        total += len(checks)
        passed += sum(checks)
        noise_exp.append(f["is_noise"]); noise_pred.append(is_noise)
        cand_exp.append(f["is_job_candidate"]); cand_pred.append(is_cand)
    return {"total": total, "passed": passed,
            "noise_prf": prf(noise_exp, noise_pred),
            "candidate_prf": prf(cand_exp, cand_pred)}


def _score_extraction(cases: list, live: bool, extractor=None) -> dict:
    """Score cached/live extraction on non-noise cases."""
    ija_exp, ija_pred = [], []
    company_hits = role_hits = 0
    status_exp, status_pred = [], []
    scored = skipped = 0
    for c in cases:
        if c.get("filters", {}).get("is_noise"):
            continue  # noise handled by the filter layer, not the LLM
        try:
            out = get_extraction(c, live=live, extractor=extractor)
        except Exception as exc:
            # Quota/transient error mid-live: stop calling the API, keep what was
            # recorded, and score the rest from cache only.
            print(f"  ! stopped live recording at '{c['id']}' ({exc}); using cache for the rest")
            live = False
            out = get_extraction(c, live=False, extractor=extractor)
        if out is None:
            print(f"  ! no cached output for '{c['id']}' — run with --live to record it")
            skipped += 1
            continue
        exp = c["expected"]
        ija_exp.append(bool(exp.get("is_job_application")))
        ija_pred.append(bool(out.get("is_job_application")))
        if exp.get("is_job_application"):
            company_hits += company_match(exp.get("company"), out.get("company"))
            role_hits += role_match(exp.get("role"), out.get("role"))
            status_exp.append(exp.get("status") or "")
            status_pred.append(out.get("status") or "")
        scored += 1
    n_app = len(status_exp)
    ija_acc = (sum(1 for e, p in zip(ija_exp, ija_pred) if e == p) / len(ija_exp)
               if ija_exp else 0.0)
    status_acc = (sum(1 for e, p in zip(status_exp, status_pred) if e == p) / n_app
                  if n_app else 0.0)
    return {
        "scored": scored, "skipped": skipped,
        "ija_accuracy": ija_acc, "ija_prf": prf(ija_exp, ija_pred),
        "company_match": company_hits / n_app if n_app else 0.0,
        "role_match": role_hits / n_app if n_app else 0.0,
        "status_accuracy": status_acc,
        "status_confusion": confusion_matrix(status_exp, status_pred, config.STATUSES),
    }


def _build_report(f: dict, e: dict) -> str:
    lines = ["# Evaluation Report", ""]
    lines.append("## Deterministic filters")
    lines.append(f"- checks passed: {f['passed']}/{f['total']}")
    lines.append(f"- noise precision/recall: {f['noise_prf'][0]:.2f} / {f['noise_prf'][1]:.2f}")
    lines.append(f"- job-candidate precision/recall: {f['candidate_prf'][0]:.2f} / {f['candidate_prf'][1]:.2f}")
    lines.append("")
    lines.append(f"## EXTRACTION (scored={e['scored']}, skipped={e['skipped']})")
    lines.append(f"- is_job_application accuracy: {e['ija_accuracy']:.2f} "
                 f"(P {e['ija_prf'][0]:.2f} / R {e['ija_prf'][1]:.2f})")
    lines.append(f"- company match: {e['company_match']:.2f}")
    lines.append(f"- role match: {e['role_match']:.2f}")
    lines.append(f"- status accuracy: {e['status_accuracy']:.2f}")
    lines.append("")
    lines.append("### Status confusion (rows=expected, cols=predicted)")
    lines.append("expected\\predicted | " + " | ".join(config.STATUSES))
    for row in config.STATUSES:
        lines.append(f"{row} | " + " | ".join(str(e["status_confusion"][row][col])
                                              for col in config.STATUSES))
    ok = (e["ija_accuracy"] >= THRESHOLDS["is_job_application"]
          and e["status_accuracy"] >= THRESHOLDS["status"]
          and e["company_match"] >= THRESHOLDS["company"])
    lines.append("")
    lines.append(f"## OVERALL: {'PASS' if ok else 'BELOW THRESHOLD'}")
    return "\n".join(lines)


def run_evals(dataset_path=DATASET_PATH, live: bool = False, extractor=None) -> dict:
    """Run the full eval suite and return a result dict including a markdown report."""
    cases = load_dataset(dataset_path)
    f = _score_filters(cases)
    e = _score_extraction(cases, live=live, extractor=extractor)
    report = _build_report(f, e)
    return {"filters": f, "extraction": e, "report": report}
