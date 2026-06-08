# Evals for the Job Application Tracker — Design Spec

**Date:** 2026-06-08
**Author:** Hiya Arora (with Claude Code)
**Status:** Approved — ready for implementation planning

## Purpose

Add an **evaluation suite** that measures how accurately the agent's AI reads an
email and extracts structured fields (`is_job_application`, `company`, `role`,
`status`). Evals turn "the tracker feels mostly right" into measurable accuracy
numbers, catch regressions when prompts change, and serve as a portfolio artifact
demonstrating QA discipline applied to an LLM (the QA→AI story).

This is "QA for AI": a golden set of example emails with known-correct answers,
run through the agent's extraction, scored against the expected answers.

## Confirmed Decisions

- **Scope:** evaluate `extract_application` (the core of discover/update) **and**
  the deterministic pipeline (`_is_noise`, `_is_job_candidate`, `_scan_priority`,
  `gmail_client._html_to_text`). Reply-draft quality (`propose_reply`) is **out of
  scope** for now; `classify_email`/`daily_task` are out of scope.
- **Dataset:** ~22 **synthetic** labeled emails (no real personal data).
- **Run mode:** LLM outputs are **cached** (recorded once, committed) so eval runs
  are free and deterministic. A `--live` flag re-records by calling Gemini.
- **Harness:** a `python main.py eval` command that prints a score table and writes
  `evals/report.md`. (Not pytest-integrated; scoring functions are unit-tested.)
- **Quota reality:** building the cache the first time costs ~16 Gemini calls (one
  per non-noise email), within one day's 20-call free quota. After that, free.

## Architecture / Files

```
evals/
├── dataset.jsonl              # ~22 synthetic labeled emails (one JSON object per line)
├── cache/extract/<id>.json    # recorded extract_application outputs (committed)
└── report.md                  # generated score report (committed sample)
jobagent/
├── evals.py                   # load dataset, score filters + extraction, build report
└── cli.py                     # add the `eval` command (--live flag)
tests/
└── test_evals.py              # unit-test scoring functions (no Gemini, no network)
```

`jobagent/evals.py` is the only new logic module. Scoring functions are pure and
testable; cache and dataset I/O are isolated helpers. The CLI command is a thin
wrapper that calls `evals.run_evals(live=...)`.

## Dataset Format (`evals/dataset.jsonl`)

One JSON object per line:

```json
{"id": "db_rejection_html", "category": "rejection",
 "email": {"sender": "db@myworkday.com",
           "subject": "Your job application with Deutsche Bank",
           "body": "<html>...the Process Reengineer, NCT position...we are not progressing...</html>"},
 "expected": {"is_job_application": true, "company": "Deutsche Bank",
              "role": "Process Reengineer, NCT", "status": "Rejected"},
 "filters": {"is_noise": false, "is_job_candidate": true, "priority": 1}}
```

- `email` — the synthetic input (sender/subject/body; body may be HTML to test
  HTML-to-text).
- `expected` — the human-labeled correct extraction. For pure-noise cases (OTP),
  `is_job_application` may be irrelevant; the case is still useful for the filter layer.
- `filters` — expected results of the deterministic checks (`is_noise`,
  `is_job_candidate`, `priority` 0/1).

### Coverage (~22 cases, mirroring real cases we hit)

- application confirmation → Applied
- rejection (plain) → Rejected
- rejection (HTML-only) → Rejected (tests HTML-to-text; the real Deutsche Bank bug)
- interview invite → Interview Scheduled
- offer → Offer
- recruiter follow-up (needs reply, no status change)
- OTP / verification email → `is_noise: true` (must be skipped, no LLM)
- course / edtech "application" (Coding Ninjas style) → `is_job_application: false`
- generic confirmation with no role (Tower/HPE style) → role null/unknown
- job alert / newsletter → `is_job_application: false`
- a couple of distinct companies to sanity-check company extraction

## Two Eval Layers

### Layer 1 — Deterministic (free, always runs live)

No Gemini. For each case, run and compare to `filters`:
- `agent._is_noise(email)` == expected `is_noise`
- `agent._is_job_candidate(email)` == expected `is_job_candidate`
- `agent._scan_priority(email)` == expected `priority`
- For HTML cases: `gmail_client._html_to_text(body)` strips tags and preserves the
  key phrases (e.g., contains "Process Reengineer, NCT" and "not progressing", no
  "<"/">").

Metrics: pass/fail counts; precision & recall for the `is_noise` and
`is_job_candidate` classifiers.

### Layer 2 — LLM extraction (cached)

For each non-noise case, obtain `extract_application(email)` output via
`get_extraction(case, live)`:
- if `live` or no cache file → call `llm.extract_application`, save to
  `evals/cache/extract/<id>.json`.
- else → load the cached JSON.

Score the output vs `expected` (see Metrics).

## Metrics & Scoring

- **is_job_application** — accuracy, plus precision/recall/F1 (catches false
  positives like course spam and false negatives).
- **company** — normalized match: lowercase, strip punctuation and common suffixes
  (Inc, Ltd, Technologies, Pvt). Pass if normalized equal.
- **role** — normalized fuzzy match: lowercase, collapse whitespace; pass if one
  normalized string contains the other or token-overlap is high. (Roles vary in
  wording; exact match is too strict.)
- **status** — exact match against the 5 statuses, **plus a confusion matrix**
  (rows = expected, cols = predicted) to surface patterns like "Rejected read as
  Applied" (the HTML bug).
- **Thresholds** (soft, shown as PASS/FAIL in the summary; tunable constants):
  `is_job_application` accuracy ≥ 0.90, `status` accuracy ≥ 0.80, `company` match
  ≥ 0.85. Only counted over cases where `is_job_application` is expected true.

## The `eval` Command

`python main.py eval [--live]`

- Default: scores cached outputs (free). `--live`: re-calls Gemini and refreshes
  the cache before scoring.
- Prints a readable table:

```
DETERMINISTIC FILTERS    22/22 passed   noise P/R 1.00/1.00   candidate P/R 0.95/1.00
EXTRACTION (cached, N=16)
  is_job_application   acc 0.94   P 0.93  R 1.00
  company match        0.88
  role match           0.81
  status accuracy      0.88
  status confusion:    [matrix]
OVERALL: PASS
```

- Writes the same content to `evals/report.md` (committed sample for the portfolio).

## Error Handling

- Missing cache file and not `--live` → clear message: "No cached output for
  `<id>`. Run `python main.py eval --live` to record it." (Continue scoring the
  rest; mark this case as skipped.)
- Malformed dataset line → warn and skip that line.
- Missing `GEMINI_API_KEY` on a `--live` run → the existing friendly key message.
- Quota error mid-`--live` → stop cleanly, keep already-recorded cache entries
  (reuses `llm`'s retry/backoff); the user re-runs `--live` next day to finish.

## Testing

`tests/test_evals.py` unit-tests the **pure scoring functions** with small
fixtures (no Gemini, no network):
- company/role/status normalization & matching
- precision/recall/F1 computation
- confusion-matrix construction
- dataset loader (parses JSONL, skips bad lines)

These run inside the normal `pytest` suite.

## Out of Scope (YAGNI)

- Reply-draft (`propose_reply`) quality scoring / LLM-as-judge.
- `classify_email` and `daily_task` evals.
- CI gating / pytest accuracy assertions (the `eval` command is the deliverable;
  could be added later).

## Portfolio Payoff

`evals/report.md` is a committed, screenshot-ready artifact, and a short
"Evaluation" section is added to the README. It demonstrates measuring an LLM's
accuracy with a labeled suite rather than trusting it blindly — the QA→AI story.
