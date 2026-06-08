# Job Application Tracker

A terminal AI assistant that manages your job search end to end:

- **Tracks every application** in a Google Sheet (your data, your account).
- **Reads your Gmail** and auto-updates each application's status (applied → interview → offer/rejected).
- **Discovers applications from your inbox** so you don't have to enter them by hand.
- **Drafts replies** to recruiters/interview invites — and only sends them after *you* approve.
- **Shows weekly metrics** (response rate, interviews, follow-ups pending) and a daily skill task.
- **Runs itself daily** via a scheduled job.

Built in Python with Google OAuth, the Gmail + Sheets APIs, and Google Gemini (free tier).

---

## How it works (architecture)

The agent is layered so each part has one job, and the data store is swappable:

```
jobagent/
├── config.py        # .env loading, OAuth scopes, constants, file paths
├── auth.py          # Google OAuth (Desktop flow) + Fernet-encrypted token storage
├── tracker.py       # Tracker (abstract interface) + SheetsTracker (Google Sheets)
├── gmail_client.py  # thin Gmail wrapper: list / read / send
├── llm.py           # Gemini: classify, extract, draft reply, daily task
├── agent.py         # orchestration: discover, sync, drafts, weekly summary
├── scheduler.py     # installs the macOS daily job (launchd)
├── setup.py         # guided first-run wizard
└── cli.py           # command-line interface
```

The key design choice: **agent logic never talks to Google directly.** It goes
through the `Tracker` interface, so you could swap the Google Sheet for SQLite by
writing one new class (`SQLiteTracker`) — no changes to the agent. Status is also
modeled as a one-way funnel (Applied → In Review → Interview Scheduled →
Rejected/Offer); it only ever moves *forward*.

---

## Prerequisites

- **Python 3.11+**
- A **Google account** (the one whose Gmail/Sheets you want to use)
- A free **Gemini API key** (from Google AI Studio)

---

## Setup

### 1. Install

```bash
cd job-application-tracker
python3 -m venv .venv
source .venv/bin/activate          # on macOS/Linux
pip install -r requirements.txt
```

(After activating the venv you can type `python main.py ...`. If you skip
activation, use `.venv/bin/python main.py ...`.)

### 2. Guided setup (recommended)

```bash
python main.py setup
```

This wizard opens each Google page in your browser, waits for you at every step,
checks that your credentials file landed, creates your `.env`, optionally captures
your Gemini key, and finishes by logging you in. If you'd rather do it by hand,
follow the manual steps below — the wizard does exactly these.

### 3. Manual setup (what the wizard automates)

**a. Create a Google Cloud project**
Go to <https://console.cloud.google.com/projectcreate>, create a project (e.g.
"Job Application Tracker"), and select it.

**b. Enable the two APIs** (off by default)
- Gmail API: <https://console.cloud.google.com/apis/library/gmail.googleapis.com> → **Enable**
- Google Sheets API: <https://console.cloud.google.com/apis/library/sheets.googleapis.com> → **Enable**

**c. Configure the OAuth consent screen**
<https://console.cloud.google.com/apis/credentials/consent>
- User type: **External**
- Fill in app name + your email.
- Under **Audience → Test users**, add the Google account you'll log in with.
  *(Skipping this is the #1 cause of "access blocked" at login.)*

**d. Create OAuth credentials**
<https://console.cloud.google.com/apis/credentials> → **Create Credentials → OAuth
client ID** → Application type **Desktop app** → **Create**. Download the JSON and
save it in the project folder as:

```
client_secret.json
```

**e. Get a Gemini API key**
<https://aistudio.google.com/apikey> → **Create API key** → copy it.

**f. Create your `.env`**

```bash
cp .env.example .env
```

Then edit `.env`:

```
GOOGLE_CLIENT_SECRETS_FILE=client_secret.json
SPREADSHEET_ID=            # leave blank — created automatically on first run
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.5-flash
```

### 4. Log in

```bash
python main.py login
```

A browser opens. Pick your account. You'll see a **"Google hasn't verified this
app"** warning — that's expected for a personal test app. Click **Advanced → Go to
… (unsafe)** and allow the permissions. Your token is encrypted and stored in
`~/.jobagent/`.

### 5. First run — the sheet is created for you

The first time you add or discover an application, the agent creates a Google
Sheet called **"Job Application Tracker"** and prints its ID. **Paste that ID into your
`.env`** as `SPREADSHEET_ID` so it reuses the same sheet next time.

---

## Commands

```bash
python main.py setup        # guided first-time setup
python main.py login        # authenticate with Google

# tracking
python main.py add --company "Acme" --role "QA Engineer" --source LinkedIn
python main.py list --since 30d --status "Interview Scheduled"

# inbox automation
python main.py discover     # find applications in your inbox and add them
python main.py update       # daily: add new + advance statuses (one scan, frugal)
python main.py sync         # optional: thorough status re-check (uses more quota)

# replies (human-approved)
python main.py drafts       # draft replies to emails needing a response

# growth
python main.py summary      # weekly dashboard
python main.py task         # a daily AI/ML-testing skill suggestion

# automation
python main.py schedule --at 09:00      # install the daily auto-run
python main.py schedule --uninstall     # remove it
```

### Run it automatically every day

```bash
python main.py schedule --at 09:00
```

On macOS this installs a **launchd** job that runs `update` once a day (whenever
your Mac is awake), logging to `~/.jobagent/daily.log`. It discovers new
applications and advances statuses with no input from you.

---

## About the Gemini free tier (important)

The free tier of `gemini-2.5-flash` is generous but limited: roughly **5
requests/minute** and a **small daily cap**. The agent is built to respect this:

- **One AI read per email, ever.** Scanned email ids are remembered
  (`~/.jobagent/seen.json`), so daily runs never re-read the same mail.
- **Gmail does the filtering for free** — only real application emails reach the AI.
- **OTP/verification emails are skipped** before any AI call.
- **Automatic backoff** waits out the per-minute limit; if the daily cap is hit it
  stops cleanly and continues the next day.

So the first backfill of many applications may complete over a day or two on the
free tier, then settle into near-zero daily cost. (You can raise the limit by
enabling billing on your Gemini key if you want instant backfill.)

---

## Where things are stored

| Path | Contents |
|------|----------|
| `~/.jobagent/key` | Fernet encryption key (private, `0600`) |
| `~/.jobagent/token.enc` | your encrypted Google token |
| `~/.jobagent/seen.json` | emails already scanned by `discover`/`update` |
| `~/.jobagent/drafts_seen.json` | emails already considered for a reply |
| `~/.jobagent/changes.log` | log of every status change |
| `~/.jobagent/daily.log` | output of the scheduled daily run |

Nothing secret is ever committed to git (`.env`, `client_secret.json`, tokens are
all gitignored).

---

## Running the tests

```bash
pip install -r requirements.txt
python -m pytest -q
```

The tests use an in-memory fake tracker and mocked Google/Gemini clients, so they
run instantly with **no network calls and no API quota**.

---

## Evaluation (measuring the AI's accuracy)

The agent's core AI task — reading an email and extracting `company`, `role`, and
`status` — is graded by an **evaluation suite** (think "QA for the AI"). A labeled
set of ~22 synthetic emails (`evals/dataset.jsonl`) covers every case the agent
must handle: confirmations, rejections (incl. HTML-only), interviews, offers,
OTP/noise, course-spam, no-role confirmations, and job alerts.

```bash
python main.py eval          # score cached model outputs (free, offline)
python main.py eval --live   # re-run the AI and refresh the cache (uses quota)
```

It reports two layers and writes `evals/report.md`:
- **Deterministic filters** (free, no AI): are noise/OTP emails skipped, are job
  emails kept, are outcome emails prioritized.
- **LLM extraction**: `is_job_application` precision/recall, company & role match,
  and **status accuracy with a confusion matrix** (e.g. how often a "Rejected" is
  misread as "Applied").

To keep within the free Gemini quota, model outputs are **cached** in
`evals/cache/` (committed), so normal eval runs are free and deterministic;
`--live` re-records when a prompt changes. This is how prompt changes are checked
for regressions before they reach your sheet.

---

## Privacy & safety

- Your emails and application data stay in **your** Google account.
- The app requests only the scopes it uses: read Gmail, send Gmail, manage
  Sheets, and your basic profile.
- **No email is ever sent automatically.** Replies are only sent after you
  explicitly approve them.
