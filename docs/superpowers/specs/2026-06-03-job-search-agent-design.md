# Job Search Agent — Design Spec

**Date:** 2026-06-03
**Author:** Hiya Arora (with Claude Code)
**Status:** Approved — ready for implementation planning

## Purpose

A terminal-only (CLI) AI agent that helps manage a job search. It tracks
applications in a Google Sheet, reads Gmail to automatically update application
statuses, drafts professional replies for human approval before sending, and
shows weekly growth metrics plus a daily AI/ML-testing skill suggestion.

This is a portfolio project demonstrating: Google OAuth, Gmail + Sheets APIs, an
LLM agent loop, a clean storage abstraction, and human-in-the-loop safety.

## Key Decisions (confirmed)

- **Interface:** terminal CLI only. No FastAPI, no web UI.
- **LLM:** Google **Gemini free tier** (`gemini-2.5-flash`), via `GEMINI_API_KEY`
  from Google AI Studio. NOT Anthropic. Free quota is low (~20 requests/day),
  so the design must minimize LLM calls.
- **Build order:** full design now; implement & verify in phases — Auth →
  Sheets Tracker → Gmail reading → Draft replies → Growth dashboard. Confirm
  each phase works before moving to the next.
- **OAuth client type:** "Desktop app" using `InstalledAppFlow.run_local_server()`
  (opens browser, catches redirect on localhost). Not a web-server redirect flow.
- **Token storage:** `token.json` encrypted at rest with `cryptography.Fernet`;
  the Fernet key lives in a separate key file with `0600` permissions. Nothing
  hardcoded, nothing secret committed to git.
- **Quota protection:** Gmail sync pre-filters emails in plain Python (match
  sender domain / company / role keywords against tracked applications) and only
  spends an LLM call on emails that already look relevant.

## Architecture

Layered CLI. Agent logic never touches Google APIs directly — it goes through
the `Tracker`, `gmail_client`, and `llm` interfaces. This keeps each module
single-purpose and the storage backend swappable.

```
jobsearch-agent/
├── jobagent/
│   ├── __init__.py
│   ├── config.py        # loads .env, paths, constants (scopes, model name)
│   ├── auth.py          # Google OAuth (InstalledAppFlow), encrypted token store, auto-refresh
│   ├── tracker.py       # ABSTRACTION: Tracker (ABC) + SheetsTracker impl + Application dataclass
│   ├── gmail_client.py  # thin Gmail API wrapper: list_recent(), get(), send()
│   ├── llm.py           # Gemini wrapper: classify_email(), draft_reply(), daily_task()
│   ├── agent.py         # orchestration: sync_inbox(), propose_drafts(), weekly_summary(), daily_task()
│   └── cli.py           # CLI commands -> calls agent + tracker
├── tests/               # pytest, with FakeTracker + mocked Google/Gemini
├── .env.example
├── requirements.txt
├── README.md
└── main.py              # entry point -> cli.main()
```

## Storage Abstraction (key requirement)

```python
@dataclass
class Application:
    company: str
    role: str
    date_applied: str        # ISO date
    source: str
    status: str              # one of STATUSES
    last_updated: str        # ISO datetime
    notes: str = ""

class Tracker(ABC):
    def add_application(self, company, role, source, date_applied=None, notes="") -> Application: ...
    def update_status(self, company, role, status, note=None) -> Application: ...
    def get_applications(self, since=None, status=None) -> list[Application]: ...
    def find_application(self, company, role) -> Application | None: ...
```

`SheetsTracker(Tracker)` implements these against a Google Sheet with columns:
**Company, Role, Date Applied, Source, Status, Last Updated, Notes**.

`STATUSES = ["Applied", "In Review", "Interview Scheduled", "Rejected", "Offer"]`

To swap to SQLite later: write `SQLiteTracker(Tracker)` and change one wiring
line. Agent code is untouched. The rest of the code only ever sees `Application`
objects, never raw spreadsheet rows.

## Auth & Token Storage

- OAuth client type **Desktop app**. `InstalledAppFlow.run_local_server()` opens
  the browser for consent and catches the redirect on localhost automatically.
- Scopes (only what the app uses):
  `openid`, `email`, `profile`,
  `https://www.googleapis.com/auth/gmail.readonly`,
  `https://www.googleapis.com/auth/gmail.send`,
  `https://www.googleapis.com/auth/spreadsheets`.
- Tokens encrypted at rest: serialized credentials JSON encrypted with
  `Fernet`. Fernet key stored at `~/.jobagent/key` (`0600`); encrypted token at
  `~/.jobagent/token.enc`.
- Auto-refresh: on load, if expired and a refresh token exists, refresh silently
  and re-save. If refresh fails, prompt the user to run `login` again.

## Data Flow — Gmail → Status Update

1. `gmail_client.list_recent(max=N)` pulls recent messages (headers + snippet).
2. **Cheap Python pre-filter:** keep only emails whose sender domain or
   subject/snippet matches a tracked company/role. Protects the Gemini quota.
3. For each surviving email → `llm.classify_email()` returns
   `{matched_company, matched_role, intent, new_status, confidence}`.
   Intents: confirmation, rejection, interview_invite, recruiter_followup, other.
4. If confidence is high and a matching application is found,
   `tracker.update_status()` updates Status + Last Updated. Every change is
   printed and appended to `~/.jobagent/changes.log`.

## AI Draft Replies (human-in-the-loop)

- `agent.propose_drafts()` finds emails needing a reply (interview_invite /
  recruiter_followup), calls `llm.draft_reply()` with the email content.
- The draft is printed to the terminal. The user chooses: **approve / edit / skip**.
- Only on explicit approval does `gmail_client.send()` send it. **Never auto-sends.**

## Growth Feature

- `agent.weekly_summary()` reads only from the Sheet: counts of applied /
  responses / interviews, response rate, follow-ups pending — printed as a small
  terminal dashboard. No LLM call.
- `agent.daily_task()` asks Gemini for one skill-learning task relevant to AI/ML
  testing roles. One LLM call per invocation.

## CLI Commands

```
jobagent login                          # run OAuth, store encrypted token
jobagent add  --company --role --source [--date] [--notes]
jobagent list [--since 30d] [--status Interview]
jobagent sync [--max 25]                # Gmail -> classify -> update Sheet
jobagent drafts                         # review & approve replies
jobagent summary                        # weekly dashboard
jobagent task                           # daily learning suggestion
```

(Invoked as `python main.py <command> ...` during development.)

## Error Handling

- Missing/empty `SPREADSHEET_ID` → auto-create the sheet (Sheets API
  `spreadsheets.create`, allowed by the `spreadsheets` scope), print the new ID,
  tell the user to paste it into `.env`.
- Expired token → silent refresh; if refresh fails → prompt to re-`login`.
- Gemini quota/rate errors → caught, logged, sync continues (that email just is
  not auto-classified this run).
- Missing `GEMINI_API_KEY` → LLM features print a friendly "set your key"
  message; tracker and Gmail features still work.

## Testing

- `pytest` with a `FakeTracker` (in-memory implementing `Tracker`) and mocked
  Google/Gemini clients — logic tested without network or quota.
- Phase 1 ships with tests for: the Tracker abstraction contract (against
  FakeTracker), date `--since` parsing, and token encrypt/decrypt round-trip.

## Configuration (.env)

```
GOOGLE_CLIENT_SECRETS_FILE=client_secret.json   # downloaded from Google Cloud
SPREADSHEET_ID=                                  # blank on first run -> auto-created
GEMINI_API_KEY=                                  # from Google AI Studio
GEMINI_MODEL=gemini-2.5-flash
```

`.env`, `client_secret.json`, `token.enc`, and the Fernet key are all
gitignored.

## Implementation Phases

1. **Auth** — `login` works, encrypted token stored, refresh works.
2. **Sheets Tracker** — create sheet, `add`, `list --since/--status`, `find`.
3. **Gmail reading + classify** — `sync`.
4. **Draft replies** — `drafts`.
5. **Growth** — `summary`, `task`.

Each phase verified in terminal/browser before the next begins (per user
instruction: do not commit a phase until verified).
