# Job Application Tracker — Complete Project Guide

**Project:** job-application-tracker (renamed from "jobsearch-agent")
**Author:** Hiya Arora (built with Claude Code)
**Repo:** https://github.com/Hiyaarora/job-application-tracker (public)
**Created:** 2026-06-03 · **Last updated:** 2026-06-07
**Status:** Working. All 5 planned features built + extras. 78 tests passing.

> This is the single "everything you need to know" doc. If someone asks *any*
> question about the project, the answer should be here, in plain language.

---

## 1. What is it? (one paragraph)

A **terminal app** that manages the *applications you've already sent*. You connect
your Gmail once. After that it reads your job-application emails, lists every
company you applied to in a **Google Sheet**, and **every morning automatically
updates each application's status** (Applied → Interview → Rejected/Offer) by
reading new emails — so you never have to dig through your inbox. It can also
**draft replies** to recruiters (you approve before anything sends) and show a
**weekly dashboard** plus a **daily skill task**.

It is **not** a job-*search* tool (it doesn't find jobs for you). It *tracks the
jobs you applied to* and keeps their status current. That's why it's named
"job-application-tracker."

---

## 2. The problem it solves

When you apply to many companies, your inbox fills with confirmations, interview
invites, and rejections. Keeping a manual tracker is tedious. This agent does it
for you: one sheet, always up to date, no manual email-checking.

---

## 3. How it works (the everyday flow)

**One-time:** you run `setup`, which connects your Google account (Gmail + Sheets)
and saves an encrypted login token on your Mac.

**Every morning at 9 AM (automatic):** a background job (`update`) runs on your
Mac and:
1. Searches Gmail for **application emails from the last 7 days** (only recruiting
   emails — not your whole inbox).
2. **Skips emails it already read** (remembered in `seen.json`) so it never wastes
   work.
3. For each *new* email, the AI reads it and either:
   - **adds a new company** (with role, date applied, status), or
   - **moves an existing company's status forward** (e.g. → Rejected).

**Whenever you want:** open the Google Sheet — it's already current. Or run
commands yourself (see §5).

> **Important nuance:** opening the sheet does **not** trigger a sync. The sheet
> is just storage; the *morning job writes into it*. By the time you open it,
> it's already been updated. The job runs on **your Mac**, so your Mac needs to be
> awake around 9 AM (if it was off, the job runs once when you next wake it, and
> because it looks back 7 days, nothing is missed).

---

## 4. The 5 core features (from the original spec)

1. **Google login (OAuth)** — secure sign-in; tokens encrypted on disk.
2. **Application tracker (Google Sheet)** — columns: Company, Role, Date Applied,
   Source, Status, Last Updated, Notes. Behind a swappable storage interface.
3. **Auto status updates from Gmail** — the AI reads emails and updates statuses.
4. **AI draft replies** — drafts replies to recruiters; **never sends without your
   approval**.
5. **Growth features** — weekly summary (response rate, interviews, pending) + a
   daily AI/ML-testing skill suggestion.

Plus extras we added: a guided **setup wizard**, **auto-discovery** of applications
from the inbox, a **daily scheduler**, and **self-healing** of rows.

---

## 5. Commands (cheat sheet)

Run from the project folder after `source .venv/bin/activate`:

| Command | What it does | Uses AI? |
|---|---|---|
| `python main.py setup` | Guided first-time Google setup (opens the pages) | no |
| `python main.py login` | Re-authenticate with Google | no |
| `python main.py add --company X --role Y --source LinkedIn` | Add an application by hand | no |
| `python main.py list [--since 7d] [--status Rejected]` | Show tracked applications | no |
| `python main.py update` | The daily job: find new + update statuses | yes |
| `python main.py discover [--company "X"] [--refresh]` | Find applications; heal one company; re-scan seen mail | yes |
| `python main.py drafts` | Draft replies to recruiters (you approve/edit/skip) | yes |
| `python main.py summary` | Weekly dashboard | no |
| `python main.py task` | A daily skill-learning suggestion | yes |
| `python main.py schedule [--at 09:00] [--uninstall]` | Install/remove the daily auto-run | no |

The two you'll use most: **`summary`** (how am I doing?) and **`update`** (refresh now).

---

## 6. Architecture (how the code is organized)

Layered, so each file has one job and the storage backend is swappable:

```
jobagent/
├── config.py        # .env loading, OAuth scopes, constants, Gmail search queries
├── auth.py          # Google OAuth + Fernet-encrypted token storage
├── tracker.py       # Tracker (interface) + SheetsTracker (Google Sheets backend)
├── gmail_client.py  # read/parse/send Gmail; HTML-to-text; dates
├── llm.py           # Gemini: classify, extract, draft, daily task (+ retry/backoff)
├── agent.py         # orchestration: discover, sync, drafts, weekly summary, self-heal
├── scheduler.py     # installs the macOS daily job (launchd)
├── setup.py         # guided first-run wizard
└── cli.py           # the command-line interface
```

**Key design idea — the storage abstraction:** agent logic never talks to Google
Sheets directly. It goes through a `Tracker` interface. Today the implementation
is `SheetsTracker` (Google Sheets); you could write `SQLiteTracker` and switch the
whole app to a local database by changing one line — no other code changes. This
is the "clean architecture" point that makes the project portfolio-worthy.

**Data flow (discover/update):** Gmail search → cheap Python filters (skip
noise/seen, prioritize informative emails) → AI reads each new email → merge per
company → write to the sheet.

---

## 7. How the AI is used (and how little)

The AI (Google Gemini) is used **only** to read an email and pull out: is this a
real job application, which company, what role, and what status. Everything else
(searching Gmail, writing the sheet, deciding what changed) is plain Python — no
AI, no cost.

To respect the tiny free quota (see §9), the agent is deliberately frugal:
- **Gmail filters first** — only real application emails reach the AI.
- **One AI read per email, ever** (`seen.json`) — daily runs are nearly free.
- **OTP/verification emails skipped** before any AI call.
- **Informative emails read first** — outcome emails (rejection/interview/offer)
  carry the role *and* the real status, so the agent gets it right within budget.

---

## 8. Key decisions & the discussions behind them

- **Terminal CLI, not a web app.** Simpler, faster to build, easy to learn from.
  (We dropped FastAPI from the original spec on purpose.)
- **Gemini free tier, not Anthropic.** To avoid cost for a portfolio project. The
  trade-off is a small daily quota (see §9).
- **One row per company.** A company's many emails (confirmation, OTP, rejection)
  collapse into a single application. Discussed because keying on company+role
  created duplicate rows (e.g. an OTP email with no role vs. a rejection with the
  role). Trade-off: if you genuinely applied to *two roles at one company*, they'd
  merge — rare for most job seekers.
- **Status only moves forward.** Applied → In Review → Interview Scheduled →
  Rejected/Offer. A stray/old email can never *downgrade* a status. This fixed a
  real bug where sync could move a "Rejected" row back to "In Review."
- **Date Applied = the email's real date** (earliest email from that company), not
  the date we discovered it. Fixed after dates showed the discovery day.
- **Strip HTML to text before the AI reads it.** Many recruiting emails are
  HTML-only; feeding raw HTML buried the role/status (this is exactly why Deutsche
  Bank's rejection was misread). Now the AI sees clean text.
- **Skip course/bootcamp/event "applications."** The AI was told to reject things
  like edtech course signups (Coding Ninjas / careercamp) that say "application"
  but aren't jobs — they were creating false rows.
- **`seen.json` + targeted `--company` / `--refresh`.** The daily job skips
  already-read emails (efficiency). To re-read and self-heal an old row, use
  `discover --company "X"` (cheap, re-scans just that company) or `--refresh`.
- **Self-healing.** When a clearer email arrives later, the agent fills a missing
  role and advances status on its own.
- **Renamed** from "jobsearch-agent" to "job-application-tracker" — it tracks
  applied jobs, it doesn't search for jobs.
- **Commits are authored as Hiya Arora only** (no AI co-author), per preference.

---

## 9. The most important limitation: the Gemini free quota

The free tier of `gemini-2.5-flash` allows roughly:
- **~5 AI reads per minute**, and
- **20 AI reads per day** (the API literally reports `quota_value: 20`).

**What this means in practice:**
- The agent can read at most ~15–20 application emails per day. If you applied to
  many places, the first backfill completes over **1–2 days** (the daily job picks
  up where it left off, thanks to `seen.json`).
- When the daily limit is hit, the agent stops cleanly and continues the next day.
- The quota **resets daily at midnight US Pacific Time (~1:30 PM IST)**.

This is the single biggest constraint and explains most "why isn't X updated yet?"
questions. It's not a bug — it's the free tier. (Options to lift it: switch to a
lighter model like `gemini-2.5-flash-lite` with higher free limits, or enable
pay-as-you-go billing — fractions of a cent per read.)

---

## 10. Where data & secrets live

| Path | Contents |
|---|---|
| Google Sheet "Job Search Tracker" | your tracked applications (the real data) |
| `~/.jobagent/key`, `token.enc` | encrypted Google login (private) |
| `~/.jobagent/seen.json` | ids of emails already read by discover/update |
| `~/.jobagent/drafts_seen.json` | emails already considered for a reply |
| `~/.jobagent/changes.log` | log of every status change |
| `~/.jobagent/daily.log` | output of the 9 AM scheduled job |
| project `.env` | your keys + spreadsheet id (gitignored) |
| project `client_secret.json` | Google OAuth credentials (gitignored) |

Nothing secret is ever committed to GitHub.

---

## 11. FAQ (real questions, plain answers)

**Q: How do I run it?**
For tracking, you don't — the 9 AM job runs itself. To run manually: `cd` into the
project, `source .venv/bin/activate`, then `python main.py <command>` (see §5).

**Q: Does the sheet update when I open it?**
No. The 9 AM job updates it beforehand; opening it just shows the latest data.

**Q: What if my Mac is off at 9 AM?**
The job runs once the next time your Mac is awake, and it looks back 7 days, so
nothing is missed (as long as you open your Mac at least once a week).

**Q: Why are only some companies listed / not all at once?**
Each company needs an AI read, and the free tier allows ~20/day. So a big backlog
fills in over 1–2 days. (As of last check, 29 of 30 recent emails were processed →
22 companies.)

**Q: Why does a company show role "(unknown)"?**
Because that company's email didn't state a role (e.g. generic "we received your
application" from Tower Research / HPE, or a third-party marketing email like
CoRover's). The agent won't invent a role. You can type it in, or a later email
that names the role will let the agent fill it automatically.

**Q: A rejection came days ago — why is the status still "Applied"?**
That email was already read once (and marked `seen`), so the daily job skips it.
If it was read while a bug was active (e.g. the HTML issue), the status got stuck.
Fix: re-scan that one company — `python main.py discover --company "X"` — which
re-reads it with the current code. (Needs a fresh daily quota.)

**Q: Will it send emails on its own?**
Never. Replies are only sent after you explicitly approve them in `drafts`.

**Q: How much does it cost?**
Nothing — it uses Google's free APIs and the free Gemini tier.

---

## 12. Glossary

- **OAuth** — the secure "Sign in with Google" flow; lets the app act for you
  without your password.
- **ATS** — Applicant Tracking System (Greenhouse, Lever, Workday, Ashby…). Most
  application emails come from these, which is how we find them precisely.
- **Gemini** — Google's AI model; reads each email and extracts the details.
- **launchd** — macOS's built-in scheduler; runs the 9 AM job.
- **Quota** — the daily limit on AI reads (≈20/day on the free tier).
- **`seen.json`** — the agent's memory of which emails it already read.

---

## 13. Status & what's left

- ✅ All 5 spec features built; 78 automated tests passing; pushed to GitHub.
- ✅ Daily auto-run installed; backfilled to 22 companies with correct dates/roles.
- ⏳ One leftover: Deutsche Bank status → Rejected (read during an earlier bug; a
  one-line `discover --company "Deutsche Bank"` fixes it once quota resets).
- 💡 Optional future ideas: an `edit` command to correct any field by hand; a
  truly always-on version via Google Apps Script (runs on Google's servers, even
  with your Mac off); higher AI quota via flash-lite or billing.
