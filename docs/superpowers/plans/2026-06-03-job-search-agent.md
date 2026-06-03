# Job Search Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A terminal CLI agent that tracks job applications in Google Sheets, auto-updates statuses from Gmail using Gemini, drafts human-approved replies, and shows growth metrics.

**Architecture:** Layered CLI. Agent logic talks only to three interfaces — `Tracker` (storage, swappable), `gmail_client` (Gmail API), and `llm` (Gemini). Google APIs are never touched directly by agent logic. Tokens are encrypted at rest; the LLM is called sparingly to respect the Gemini free quota.

**Tech Stack:** Python 3.11+, `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `google-generativeai`, `cryptography`, `python-dotenv`, `pytest`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `main.py` | Entry point → `jobagent.cli.main()` |
| `jobagent/config.py` | Load `.env`, paths under `~/.jobagent/`, constants (scopes, statuses, model) |
| `jobagent/auth.py` | OAuth `InstalledAppFlow`, Fernet-encrypted token store, auto-refresh, build API services |
| `jobagent/tracker.py` | `Application` dataclass, `Tracker` ABC, `SheetsTracker` impl |
| `jobagent/gmail_client.py` | `list_recent()`, `get_message()`, `send_message()` |
| `jobagent/llm.py` | Gemini wrapper: `classify_email()`, `draft_reply()`, `daily_task()` |
| `jobagent/agent.py` | Orchestration: `sync_inbox()`, `propose_drafts()`, `weekly_summary()`, `daily_task()` |
| `jobagent/cli.py` | argparse command dispatch |
| `tests/` | `FakeTracker` + mocked clients |

---

## Phase 0: Project Scaffolding

### Task 0: Skeleton, deps, env template

**Files:**
- Create: `requirements.txt`, `.env.example`, `jobagent/__init__.py`, `main.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Write `requirements.txt`**

```
google-auth==2.35.0
google-auth-oauthlib==1.2.1
google-api-python-client==2.149.0
google-generativeai==0.8.3
cryptography==43.0.1
python-dotenv==1.0.1
pytest==8.3.3
```

- [ ] **Step 2: Write `.env.example`**

```
# Path to the OAuth client secrets JSON downloaded from Google Cloud Console
GOOGLE_CLIENT_SECRETS_FILE=client_secret.json
# Leave blank on first run; the app creates a sheet and prints the ID to paste here
SPREADSHEET_ID=
# Get from https://aistudio.google.com/apikey
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
```

- [ ] **Step 3: Create `jobagent/__init__.py`, `tests/__init__.py` (empty), and `main.py`**

```python
# main.py
from jobagent.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create venv and install**

Run: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
Expected: installs without error.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example jobagent/__init__.py main.py tests/__init__.py
git commit -m "chore: scaffold project deps and env template"
```

---

## Phase 1: Auth

### Task 1: `config.py` — paths and constants

**Files:**
- Create: `jobagent/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from jobagent import config

def test_scopes_only_what_we_use():
    assert config.SCOPES == [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/spreadsheets",
    ]

def test_statuses_defined():
    assert config.STATUSES == [
        "Applied", "In Review", "Interview Scheduled", "Rejected", "Offer",
    ]

def test_app_dir_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    importlib.reload(config)
    assert str(config.APP_DIR).startswith(str(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError` / attributes missing.

- [ ] **Step 3: Write `jobagent/config.py`**

```python
"""Central configuration: env loading, file paths, and constants."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # read .env from current working directory if present

# OAuth scopes — ONLY what this app actually uses.
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]

# Valid application statuses (also the Sheet's allowed Status values).
STATUSES = ["Applied", "In Review", "Interview Scheduled", "Rejected", "Offer"]

# Spreadsheet header row, in column order.
SHEET_HEADERS = [
    "Company", "Role", "Date Applied", "Source",
    "Status", "Last Updated", "Notes",
]
SHEET_TAB = "Applications"

# Where we keep secrets/state (created on demand, 0700).
APP_DIR = Path(os.path.expanduser("~")) / ".jobagent"
KEY_FILE = APP_DIR / "key"           # Fernet key, 0600
TOKEN_FILE = APP_DIR / "token.enc"   # encrypted OAuth credentials
CHANGES_LOG = APP_DIR / "changes.log"

# From .env
CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secret.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()


def ensure_app_dir() -> None:
    """Create ~/.jobagent with private permissions if missing."""
    APP_DIR.mkdir(mode=0o700, exist_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jobagent/config.py tests/test_config.py
git commit -m "feat(config): scopes, statuses, paths, env loading"
```

### Task 2: `auth.py` — encrypted token store (round-trip)

**Files:**
- Create: `jobagent/auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test** (test encryption round-trip in isolation, no network)

```python
# tests/test_auth.py
import json
from jobagent import auth, config

def test_token_encrypt_decrypt_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(config, "TOKEN_FILE", tmp_path / "token.enc")

    payload = {"token": "abc", "refresh_token": "xyz"}
    auth._save_encrypted(payload)
    loaded = auth._load_encrypted()
    assert loaded == payload

def test_key_file_permissions_are_private(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(config, "TOKEN_FILE", tmp_path / "token.enc")
    auth._save_encrypted({"a": 1})
    mode = (tmp_path / "key").stat().st_mode & 0o777
    assert mode == 0o600

def test_load_returns_none_when_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "key")
    monkeypatch.setattr(config, "TOKEN_FILE", tmp_path / "token.enc")
    assert auth._load_encrypted() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: FAIL — module/functions missing.

- [ ] **Step 3: Write `jobagent/auth.py`**

```python
"""Google OAuth (Desktop app flow) with Fernet-encrypted token storage."""
import json
import os
from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import config


def _get_fernet() -> Fernet:
    """Load the Fernet key, generating it (0600) on first use."""
    config.ensure_app_dir()
    if not config.KEY_FILE.exists():
        key = Fernet.generate_key()
        # Write then tighten perms so the key is owner-only.
        config.KEY_FILE.write_bytes(key)
        os.chmod(config.KEY_FILE, 0o600)
    return Fernet(config.KEY_FILE.read_bytes())


def _save_encrypted(payload: dict) -> None:
    """Encrypt a dict to TOKEN_FILE (0600)."""
    config.ensure_app_dir()
    token = _get_fernet().encrypt(json.dumps(payload).encode())
    config.TOKEN_FILE.write_bytes(token)
    os.chmod(config.TOKEN_FILE, 0o600)


def _load_encrypted() -> dict | None:
    """Decrypt TOKEN_FILE, or None if it doesn't exist."""
    if not config.TOKEN_FILE.exists():
        return None
    data = _get_fernet().decrypt(config.TOKEN_FILE.read_bytes())
    return json.loads(data.decode())


def login() -> Credentials:
    """Run the browser OAuth consent flow and store the encrypted token."""
    flow = InstalledAppFlow.from_client_secrets_file(
        config.CLIENT_SECRETS_FILE, scopes=config.SCOPES
    )
    creds = flow.run_local_server(port=0)
    _save_encrypted(json.loads(creds.to_json()))
    return creds


def get_credentials() -> Credentials:
    """Load stored creds, refreshing silently if expired. Raise if no login yet."""
    payload = _load_encrypted()
    if payload is None:
        raise RuntimeError("Not logged in. Run: python main.py login")
    creds = Credentials.from_authorized_user_info(payload, config.SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_encrypted(json.loads(creds.to_json()))
    return creds


def sheets_service():
    """Return an authorized Sheets API client."""
    return build("sheets", "v4", credentials=get_credentials())


def gmail_service():
    """Return an authorized Gmail API client."""
    return build("gmail", "v1", credentials=get_credentials())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add jobagent/auth.py tests/test_auth.py
git commit -m "feat(auth): Fernet-encrypted token store + OAuth flow"
```

### Task 3: `cli.py` — `login` command (manual verification)

**Files:**
- Create: `jobagent/cli.py`

- [ ] **Step 1: Write minimal `jobagent/cli.py` with a `login` command**

```python
"""Command-line interface for the Job Search Agent."""
import argparse

from . import auth


def cmd_login(args):
    auth.login()
    print("Login successful. Encrypted token stored in ~/.jobagent/")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobagent", description="AI Job Search Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Authenticate with Google").set_defaults(func=cmd_login)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
```

- [ ] **Step 2: Manual verification (requires Google Cloud setup from README)**

Run: `.venv/bin/python main.py login`
Expected: browser opens, consent granted, prints "Login successful." and `~/.jobagent/token.enc` exists.

> **STOP — verify in browser before continuing (per user instruction: do not commit a phase until verified).**

- [ ] **Step 3: Commit**

```bash
git add jobagent/cli.py
git commit -m "feat(cli): login command"
```

### Task 3b: `setup.py` — guided setup wizard (added on request)

**Files:**
- Create: `jobagent/setup.py`, `tests/test_setup.py`, `tests/test_setup_flow.py`
- Modify: `jobagent/cli.py` (add `setup` command)

A `python main.py setup` wizard that opens each Google Cloud / AI Studio page in
the browser, waits at every step, verifies `client_secret.json` landed, creates
`.env` from the template, optionally captures the Gemini key, and finishes by
running `login`. Pure helpers (`ensure_env_file`, `set_env_var`) are TDD'd; the
interactive `run_setup()` takes injectable `opener`/`prompt`/`out` so the flow is
testable without a real browser or stdin.

- [ ] Tests for `ensure_env_file`, `set_env_var`, and a flow test asserting the
  right URLs are opened and `.env` is created.
- [ ] Implement `setup.py`; wire `cmd_setup` + `setup` subcommand in `cli.py`.
- [ ] Commit `feat(setup): guided browser-based setup wizard`.

---

## Phase 2: Sheets Tracker

### Task 4: `tracker.py` — `Application` + `Tracker` ABC + `FakeTracker` tests

**Files:**
- Create: `jobagent/tracker.py`, `tests/fakes.py`
- Test: `tests/test_tracker_contract.py`

- [ ] **Step 1: Write `tests/fakes.py` (in-memory Tracker for tests)**

```python
# tests/fakes.py
from datetime import datetime, timezone
from jobagent.tracker import Tracker, Application


class FakeTracker(Tracker):
    """In-memory Tracker for tests — no network."""
    def __init__(self):
        self._rows: list[Application] = []

    def add_application(self, company, role, source, date_applied=None, notes=""):
        now = datetime.now(timezone.utc)
        app = Application(
            company=company, role=role,
            date_applied=date_applied or now.date().isoformat(),
            source=source, status="Applied",
            last_updated=now.isoformat(timespec="seconds"), notes=notes,
        )
        self._rows.append(app)
        return app

    def update_status(self, company, role, status, note=None):
        app = self.find_application(company, role)
        if app is None:
            raise KeyError(f"{company}/{role} not found")
        app.status = status
        app.last_updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if note:
            app.notes = (app.notes + " | " + note).strip(" |")
        return app

    def get_applications(self, since=None, status=None):
        rows = self._rows
        if status:
            rows = [r for r in rows if r.status == status]
        if since:
            rows = [r for r in rows if r.date_applied >= since.date().isoformat()]
        return list(rows)

    def find_application(self, company, role):
        for r in self._rows:
            if r.company.lower() == company.lower() and r.role.lower() == role.lower():
                return r
        return None
```

- [ ] **Step 2: Write the failing contract test**

```python
# tests/test_tracker_contract.py
from datetime import datetime, timedelta, timezone
from tests.fakes import FakeTracker


def test_add_and_find():
    t = FakeTracker()
    t.add_application("Acme", "QA Engineer", "LinkedIn")
    found = t.find_application("acme", "qa engineer")  # case-insensitive
    assert found is not None
    assert found.status == "Applied"

def test_update_status():
    t = FakeTracker()
    t.add_application("Acme", "QA Engineer", "LinkedIn")
    t.update_status("Acme", "QA Engineer", "Rejected", note="auto from email")
    assert t.find_application("Acme", "QA Engineer").status == "Rejected"

def test_get_filtered_by_status():
    t = FakeTracker()
    t.add_application("Acme", "QA", "LinkedIn")
    t.add_application("Beta", "SDET", "Referral")
    t.update_status("Beta", "SDET", "Offer")
    assert [a.company for a in t.get_applications(status="Offer")] == ["Beta"]

def test_get_filtered_since():
    t = FakeTracker()
    t.add_application("Old", "QA", "Web", date_applied="2000-01-01")
    t.add_application("New", "QA", "Web")
    since = datetime.now(timezone.utc) - timedelta(days=1)
    assert [a.company for a in t.get_applications(since=since)] == ["New"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_tracker_contract.py -v`
Expected: FAIL — `jobagent.tracker` has no `Tracker`/`Application`.

- [ ] **Step 4: Write `jobagent/tracker.py` (ABC + dataclass only; SheetsTracker in next task)**

```python
"""Storage abstraction. Agent logic depends on Tracker, never on Sheets directly."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Application:
    company: str
    role: str
    date_applied: str   # ISO date, e.g. "2026-06-03"
    source: str
    status: str
    last_updated: str   # ISO datetime
    notes: str = ""


class Tracker(ABC):
    """Backend-agnostic interface for the application store."""

    @abstractmethod
    def add_application(self, company: str, role: str, source: str,
                        date_applied: str | None = None, notes: str = "") -> Application: ...

    @abstractmethod
    def update_status(self, company: str, role: str, status: str,
                      note: str | None = None) -> Application: ...

    @abstractmethod
    def get_applications(self, since: datetime | None = None,
                         status: str | None = None) -> list[Application]: ...

    @abstractmethod
    def find_application(self, company: str, role: str) -> Application | None: ...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_tracker_contract.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add jobagent/tracker.py tests/fakes.py tests/test_tracker_contract.py
git commit -m "feat(tracker): Application dataclass + Tracker ABC + FakeTracker tests"
```

### Task 5: `SheetsTracker` implementation

**Files:**
- Modify: `jobagent/tracker.py` (append `SheetsTracker`)
- Test: `tests/test_sheets_tracker.py` (mock the Sheets service)

- [ ] **Step 1: Write the failing test using a mocked Sheets service**

```python
# tests/test_sheets_tracker.py
from unittest.mock import MagicMock
from jobagent.tracker import SheetsTracker


def _mock_service(rows):
    """Build a fake Sheets service whose values().get() returns `rows`."""
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {"values": rows}
    values.append.return_value.execute.return_value = {}
    values.update.return_value.execute.return_value = {}
    return service


def test_get_applications_parses_rows():
    rows = [
        ["Company", "Role", "Date Applied", "Source", "Status", "Last Updated", "Notes"],
        ["Acme", "QA", "2026-06-01", "LinkedIn", "Applied", "2026-06-01T10:00:00", ""],
    ]
    t = SheetsTracker(_mock_service(rows), spreadsheet_id="sheet123")
    apps = t.get_applications()
    assert len(apps) == 1
    assert apps[0].company == "Acme"

def test_add_application_appends_row():
    t = SheetsTracker(_mock_service([["Company", "Role", "Date Applied", "Source",
                                      "Status", "Last Updated", "Notes"]]),
                      spreadsheet_id="sheet123")
    app = t.add_application("Beta", "SDET", "Referral")
    assert app.status == "Applied"
    t.service.spreadsheets.return_value.values.return_value.append.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_sheets_tracker.py -v`
Expected: FAIL — `SheetsTracker` not defined.

- [ ] **Step 3: Append `SheetsTracker` to `jobagent/tracker.py`**

```python
from datetime import timezone
from . import config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SheetsTracker(Tracker):
    """Tracker backed by a Google Sheet. One row per application."""

    def __init__(self, service, spreadsheet_id: str):
        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.tab = config.SHEET_TAB

    # --- low-level helpers ---
    def _all_rows(self) -> list[list[str]]:
        resp = (self.service.spreadsheets().values()
                .get(spreadsheetId=self.spreadsheet_id, range=self.tab)
                .execute())
        return resp.get("values", [])

    def _to_app(self, row: list[str]) -> Application:
        padded = row + [""] * (len(config.SHEET_HEADERS) - len(row))
        return Application(*padded[:len(config.SHEET_HEADERS)])

    # --- Tracker interface ---
    def add_application(self, company, role, source, date_applied=None, notes=""):
        app = Application(
            company=company, role=role,
            date_applied=date_applied or _now_iso()[:10],
            source=source, status="Applied",
            last_updated=_now_iso(), notes=notes,
        )
        body = {"values": [[app.company, app.role, app.date_applied, app.source,
                            app.status, app.last_updated, app.notes]]}
        (self.service.spreadsheets().values()
         .append(spreadsheetId=self.spreadsheet_id, range=self.tab,
                 valueInputOption="USER_ENTERED", body=body)
         .execute())
        return app

    def get_applications(self, since=None, status=None):
        rows = self._all_rows()
        apps = [self._to_app(r) for r in rows[1:]]  # skip header
        if status:
            apps = [a for a in apps if a.status == status]
        if since:
            apps = [a for a in apps if a.date_applied >= since.date().isoformat()]
        return apps

    def find_application(self, company, role):
        rows = self._all_rows()
        for r in rows[1:]:
            app = self._to_app(r)
            if (app.company.lower() == company.lower()
                    and app.role.lower() == role.lower()):
                return app
        return None

    def update_status(self, company, role, status, note=None):
        rows = self._all_rows()
        for idx, r in enumerate(rows[1:], start=2):  # 1-based + header
            app = self._to_app(r)
            if (app.company.lower() == company.lower()
                    and app.role.lower() == role.lower()):
                app.status = status
                app.last_updated = _now_iso()
                if note:
                    app.notes = (app.notes + " | " + note).strip(" |")
                body = {"values": [[app.company, app.role, app.date_applied,
                                    app.source, app.status, app.last_updated, app.notes]]}
                (self.service.spreadsheets().values()
                 .update(spreadsheetId=self.spreadsheet_id,
                         range=f"{self.tab}!A{idx}:G{idx}",
                         valueInputOption="USER_ENTERED", body=body)
                 .execute())
                return app
        raise KeyError(f"{company}/{role} not found")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_sheets_tracker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jobagent/tracker.py tests/test_sheets_tracker.py
git commit -m "feat(tracker): SheetsTracker backed by Google Sheets"
```

### Task 6: Sheet bootstrap + wiring helper

**Files:**
- Modify: `jobagent/tracker.py` (add `get_or_create_sheet`)
- Test: `tests/test_sheet_bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sheet_bootstrap.py
from unittest.mock import MagicMock
from jobagent.tracker import get_or_create_sheet


def test_creates_sheet_when_no_id():
    service = MagicMock()
    create = service.spreadsheets.return_value.create.return_value
    create.execute.return_value = {"spreadsheetId": "new123"}
    values = service.spreadsheets.return_value.values.return_value
    values.update.return_value.execute.return_value = {}

    sid = get_or_create_sheet(service, "")
    assert sid == "new123"
    values.update.assert_called_once()  # header row written

def test_returns_existing_id():
    service = MagicMock()
    assert get_or_create_sheet(service, "existing") == "existing"
    service.spreadsheets.return_value.create.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_sheet_bootstrap.py -v`
Expected: FAIL — `get_or_create_sheet` not defined.

- [ ] **Step 3: Append to `jobagent/tracker.py`**

```python
def get_or_create_sheet(service, spreadsheet_id: str) -> str:
    """Return an existing spreadsheet id, or create a new sheet with headers."""
    if spreadsheet_id:
        return spreadsheet_id
    created = (service.spreadsheets().create(body={
        "properties": {"title": "Job Search Tracker"},
        "sheets": [{"properties": {"title": config.SHEET_TAB}}],
    }).execute())
    sid = created["spreadsheetId"]
    (service.spreadsheets().values()
     .update(spreadsheetId=sid, range=f"{config.SHEET_TAB}!A1:G1",
             valueInputOption="RAW", body={"values": [config.SHEET_HEADERS]})
     .execute())
    return sid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_sheet_bootstrap.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jobagent/tracker.py tests/test_sheet_bootstrap.py
git commit -m "feat(tracker): auto-create sheet with headers on first run"
```

### Task 7: CLI `add` and `list` + `--since` parsing

**Files:**
- Create: `jobagent/dates.py` (parse "30d" style intervals)
- Modify: `jobagent/cli.py`
- Test: `tests/test_dates.py`

- [ ] **Step 1: Write the failing test for date parsing**

```python
# tests/test_dates.py
from datetime import datetime, timezone
from jobagent.dates import parse_since


def test_parse_days():
    base = datetime(2026, 6, 3, tzinfo=timezone.utc)
    assert parse_since("30d", now=base).date().isoformat() == "2026-05-04"

def test_parse_none_returns_none():
    assert parse_since(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_dates.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write `jobagent/dates.py`**

```python
"""Parse simple relative intervals like '30d', '2w' into a cutoff datetime."""
import re
from datetime import datetime, timedelta, timezone

_UNITS = {"d": 1, "w": 7}


def parse_since(text: str | None, now: datetime | None = None) -> datetime | None:
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    m = re.fullmatch(r"(\d+)\s*([dw])", text.strip().lower())
    if not m:
        raise ValueError(f"Bad interval: {text!r}. Use e.g. '30d' or '2w'.")
    return now - timedelta(days=int(m.group(1)) * _UNITS[m.group(2)])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_dates.py -v`
Expected: PASS.

- [ ] **Step 5: Add a Tracker factory + `add`/`list` commands to `cli.py`**

```python
# add near top of jobagent/cli.py
from . import auth, config
from .tracker import SheetsTracker, get_or_create_sheet
from .dates import parse_since


def _tracker() -> SheetsTracker:
    service = auth.sheets_service()
    sid = get_or_create_sheet(service, config.SPREADSHEET_ID)
    if sid != config.SPREADSHEET_ID:
        print(f"Created a new sheet. Add this to your .env:\n  SPREADSHEET_ID={sid}")
    return SheetsTracker(service, sid)


def cmd_add(args):
    app = _tracker().add_application(args.company, args.role, args.source, notes=args.notes or "")
    print(f"Added: {app.company} — {app.role} [{app.status}]")


def cmd_list(args):
    since = parse_since(args.since)
    apps = _tracker().get_applications(since=since, status=args.status)
    if not apps:
        print("No applications found.")
        return
    for a in apps:
        print(f"{a.date_applied}  {a.company:20} {a.role:25} {a.status:20} {a.notes}")
```

- [ ] **Step 6: Register the commands in `build_parser()`**

```python
    a = sub.add_parser("add", help="Add an application")
    a.add_argument("--company", required=True)
    a.add_argument("--role", required=True)
    a.add_argument("--source", required=True)
    a.add_argument("--notes")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="List applications")
    l.add_argument("--since", help="e.g. 30d, 2w")
    l.add_argument("--status", choices=config.STATUSES)
    l.set_defaults(func=cmd_list)
```

- [ ] **Step 7: Run full test suite**

Run: `.venv/bin/pytest -v`
Expected: all PASS.

- [ ] **Step 8: Manual verification**

Run: `.venv/bin/python main.py add --company Acme --role "QA Engineer" --source LinkedIn`
then `.venv/bin/python main.py list --since 30d`
Expected: row appears in your Google Sheet and in the list output.

> **STOP — verify in browser/Sheet before continuing.**

- [ ] **Step 9: Commit**

```bash
git add jobagent/dates.py jobagent/cli.py tests/test_dates.py
git commit -m "feat(cli): add and list commands with --since/--status"
```

---

## Phase 3: Gmail Reading + Classify

### Task 8: `gmail_client.py`

**Files:**
- Create: `jobagent/gmail_client.py`
- Test: `tests/test_gmail_client.py` (mock the Gmail service)

- [ ] **Step 1: Write failing tests** for `list_recent()` (returns parsed `{id, sender, subject, snippet}`) and `parse_message()` (extracts headers + plain-text body from a Gmail message payload). Use a mocked service like Task 5.
- [ ] **Step 2: Run to confirm failure.**
- [ ] **Step 3: Implement** `list_recent(service, max_results)`, `get_message(service, msg_id)`, `parse_message(raw)` (walk `payload.parts`, base64url-decode `text/plain`), and `send_message(service, to, subject, body, thread_id=None)` (build a MIME message, base64url-encode, `users().messages().send`).
- [ ] **Step 4: Run tests — PASS.**
- [ ] **Step 5: Commit** `feat(gmail): list/get/parse/send wrappers`.

### Task 9: `llm.py` — Gemini classify

**Files:**
- Create: `jobagent/llm.py`
- Test: `tests/test_llm.py` (mock `google.generativeai`)

- [ ] **Step 1: Write failing test** asserting `classify_email()` parses the model's JSON into `{matched_company, matched_role, intent, new_status, confidence}` and that a missing `GEMINI_API_KEY` raises a clear error.
- [ ] **Step 2: Confirm failure.**
- [ ] **Step 3: Implement** `_model()` (configure with `config.GEMINI_API_KEY`, raise friendly error if blank), `classify_email(email, candidates)` — prompt includes the tracked company/role candidates and the email; request JSON; parse defensively. Map intents → statuses: `rejection→Rejected`, `interview_invite→Interview Scheduled`, `confirmation→In Review`, others→no change.
- [ ] **Step 4: Run tests — PASS.**
- [ ] **Step 5: Commit** `feat(llm): Gemini email classifier`.

### Task 10: `agent.sync_inbox()` + CLI `sync`

**Files:**
- Create: `jobagent/agent.py`
- Modify: `jobagent/cli.py`
- Test: `tests/test_agent_sync.py` (FakeTracker + fake gmail/llm callables)

- [ ] **Step 1: Write failing test** for `sync_inbox(tracker, emails, classifier)` proving: (a) the **Python pre-filter** keeps only emails matching a tracked company/sender-domain/role; (b) only pre-filtered emails are passed to the classifier (assert call count); (c) a high-confidence classification calls `update_status`; (d) low confidence does not.
- [ ] **Step 2: Confirm failure.**
- [ ] **Step 3: Implement** `_prefilter(emails, apps)` (substring/domain match) and `sync_inbox(...)` that pre-filters, classifies survivors, updates the tracker on high confidence, and appends each change to `config.CHANGES_LOG`. Then add `cmd_sync` wiring `auth.gmail_service()` + `_tracker()` + `llm.classify_email`.
- [ ] **Step 4: Run tests — PASS.**
- [ ] **Step 5: Manual verification** — `python main.py sync --max 25`; confirm a real status change appears in the Sheet and `changes.log`. **STOP and verify.**
- [ ] **Step 6: Commit** `feat(agent): Gmail sync with quota-safe pre-filter`.

---

## Phase 4: Draft Replies (human-in-the-loop)

### Task 11: `llm.draft_reply()` + `agent.propose_drafts()` + CLI `drafts`

**Files:**
- Modify: `jobagent/llm.py`, `jobagent/agent.py`, `jobagent/cli.py`
- Test: `tests/test_drafts.py`

- [ ] **Step 1: Write failing test** for `draft_reply(email)` (returns a string draft from mocked Gemini) and for an approval helper `review_draft(draft, input_fn, edit_fn)` proving: approve → returns draft; skip → returns None; edit → returns edited text. Inject `input_fn` so no real stdin.
- [ ] **Step 2: Confirm failure.**
- [ ] **Step 3: Implement** `draft_reply()` in `llm.py`; `propose_drafts(tracker, emails, classifier, drafter)` selecting `interview_invite`/`recruiter_followup` emails; `review_draft()` printing the draft and prompting `[a]pprove / [e]dit / [s]kip`. `cmd_drafts` sends via `gmail_client.send_message` **only** on approve.
- [ ] **Step 4: Run tests — PASS.**
- [ ] **Step 5: Manual verification** — run `python main.py drafts`, approve one reply to yourself, confirm it sends; skip another, confirm nothing sends. **STOP and verify.**
- [ ] **Step 6: Commit** `feat(drafts): AI reply drafting with explicit approval before send`.

---

## Phase 5: Growth

### Task 12: `agent.weekly_summary()` + `daily_task()` + CLI `summary`/`task`

**Files:**
- Modify: `jobagent/agent.py`, `jobagent/llm.py`, `jobagent/cli.py`
- Test: `tests/test_growth.py`

- [ ] **Step 1: Write failing test** for `weekly_summary(tracker, now)` computing counts (applied, responses, interviews), response rate, and follow-ups pending from a FakeTracker — assert the returned dict values. And `daily_task()` returns a non-empty string from mocked Gemini.
- [ ] **Step 2: Confirm failure.**
- [ ] **Step 3: Implement** `weekly_summary()` (pure computation over `get_applications`), a printer in `cli.py`, and `daily_task()` in `llm.py` (single Gemini call, fixed prompt for an AI/ML-testing skill task). Add `cmd_summary`, `cmd_task`.
- [ ] **Step 4: Run tests — PASS.**
- [ ] **Step 5: Manual verification** — `python main.py summary` and `python main.py task`. **STOP and verify.**
- [ ] **Step 6: Commit** `feat(growth): weekly summary dashboard + daily skill task`.

---

## Phase 6: Docs

### Task 13: README + final polish

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`** with step-by-step setup: create a Google Cloud project; enable **Gmail API** and **Google Sheets API**; configure the OAuth consent screen as **External** and add your own email as a **test user**; create **Desktop app** OAuth credentials and download `client_secret.json`; get a `GEMINI_API_KEY` from Google AI Studio; copy `.env.example` → `.env`; run `python main.py login`; run `add`/`list`/`sync`/`drafts`/`summary`/`task`; note the first-run flow where the app prints a new `SPREADSHEET_ID` to paste into `.env`; note the Gemini free-quota limit.
- [ ] **Step 2: Run full suite** `.venv/bin/pytest -v` — all PASS.
- [ ] **Step 3: Commit** `docs: setup README`.

---

## Self-Review Notes

- **Spec coverage:** OAuth+scopes (Task 1–3), encrypted token+refresh (Task 2), Tracker abstraction (Task 4), Sheets backend + auto-create (Task 5–6), manual add/list with filters (Task 7), Gmail read+classify+auto-update+log (Task 8–10), quota pre-filter (Task 10), human-approved drafts (Task 11), growth summary + daily task (Task 12), README with full Google Cloud setup (Task 13). All spec sections mapped.
- **Type consistency:** `Application` field order is fixed and reused by `SheetsTracker` row builders, `_to_app`, and `FakeTracker`. `classify_email()` return keys (`matched_company, matched_role, intent, new_status, confidence`) are consumed unchanged by `sync_inbox`.
- **Quota:** only `sync` (post-filter), `drafts`, and `task` call Gemini; `summary`, `add`, `list` never do.
