# Job Application Tracker

A terminal AI assistant that runs your job search from your inbox and a Google Sheet.

- **Tracks every application** in a Google Sheet (your account, your data).
- **Discovers applications** automatically from your Gmail — no manual entry.
- **Updates statuses** as emails arrive (Applied → In Review → Interview → Offer/Rejected).
- **Drafts replies** to recruiters — sent only after you approve.
- **Weekly metrics + a daily skill task** to keep momentum.
- **Runs daily on its own** via a scheduled job.

Built in Python with Google OAuth, the Gmail + Sheets APIs, and Google Gemini (free tier).

---

## Prerequisites

- Python 3.11+
- A Google account (whose Gmail/Sheets you'll use)
- A free Gemini API key ([Google AI Studio](https://aistudio.google.com/apikey))

---

## Install

```bash
cd job-application-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Setup

**Fastest:** run the guided wizard, which walks through every step below and creates your `.env`:

```bash
python main.py setup
```

**Manual (Google OAuth):** if you'd rather do it yourself:

1. **Create a project** at [Google Cloud Console](https://console.cloud.google.com/projectcreate).
2. **Enable two APIs:** [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) and [Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com).
3. **Configure the OAuth consent screen** ([link](https://console.cloud.google.com/apis/credentials/consent)): User type **External**, then add your Google account under **Test users** *(skipping this causes "access blocked" at login)*.
4. **Create credentials** ([link](https://console.cloud.google.com/apis/credentials)) → **OAuth client ID** → **Desktop app**. Download the JSON and save it as `client_secret.json` in the project folder.
5. **Create your `.env`** from the template and fill in your Gemini key:

   ```bash
   cp .env.example .env
   ```
   ```
   GOOGLE_CLIENT_SECRETS_FILE=client_secret.json
   SPREADSHEET_ID=            # leave blank — created on first run
   GEMINI_API_KEY=your-key-here
   GEMINI_MODEL=gemini-2.5-flash
   ```

**Log in:**

```bash
python main.py login
```

A browser opens — pick your account and allow access. (The "Google hasn't verified this app" warning is expected for a personal app: **Advanced → Go to … (unsafe)**.) The token is encrypted in `~/.jobagent/`.

On your first `add`/`discover`, a sheet named **"Job Application Tracker"** is created and its ID printed — paste that into `.env` as `SPREADSHEET_ID` to reuse it.

---

## Commands

```bash
# tracking
python main.py add --company "Acme" --role "QA Engineer" --source LinkedIn
python main.py list --since 30d --status "Interview Scheduled"

# inbox automation
python main.py discover     # find applications in your inbox and add them
python main.py update       # daily: add new + advance statuses (frugal, one scan)
python main.py sync         # thorough status re-check (uses more quota)

# replies (human-approved)
python main.py drafts       # draft replies to emails needing a response

# growth
python main.py summary      # weekly dashboard
python main.py task         # daily AI/ML-testing skill suggestion

# automation
python main.py schedule --at 09:00     # install daily auto-run (macOS launchd)
python main.py schedule --uninstall    # remove it
```

The scheduled job runs `update` once a day and logs to `~/.jobagent/daily.log`.

---

## Notes

- **Gemini free tier** (~5 req/min + small daily cap): the agent reads each email only once (`~/.jobagent/seen.json`), filters via Gmail before any AI call, skips OTP/noise, and backs off automatically. A large first backfill may finish over a day or two, then costs near zero.
- **Privacy:** data stays in your Google account; only the scopes used are requested; **no email is sent without your approval**. Secrets (`.env`, `client_secret.json`, tokens) are gitignored.
- **Architecture:** agent logic talks to a `Tracker` interface, not Google directly — so the Google Sheet backend is swappable (e.g. SQLite) without touching the agent.

---

## Tests & Evaluation

```bash
python -m pytest -q      # fast, fully mocked — no network or quota
python main.py eval      # score the AI's email-extraction accuracy (offline, cached)
python main.py eval --live   # re-run the AI and refresh the cache (uses quota)
```

The eval suite grades the core AI task (extract `company`, `role`, `status` from an email) against a labeled set, reporting precision/recall and a status confusion matrix. Outputs are cached so runs are free and deterministic; `--live` re-records when prompts change.
