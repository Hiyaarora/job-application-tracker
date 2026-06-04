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

# A precise Gmail search for real application emails — known recruiting systems
# (ATS) plus strong subject phrases. Used by `discover` so we spend scarce LLM
# calls only on high-signal mail instead of the whole inbox.
APPLICATION_QUERY = (
    "from:greenhouse.io OR from:greenhouse-mail.io OR from:hire.lever.co OR "
    "from:myworkday.com OR from:ashbyhq.com OR from:smartrecruiters.com OR "
    "from:icims.com OR from:jobvite.com OR from:bamboohr.com OR from:wellfound.com OR "
    "from:rippling.com OR from:workable.com OR from:recruitee.com OR from:turbohire.co OR "
    'subject:"your application" OR subject:"thank you for applying" OR '
    'subject:"application received" OR subject:"we received your application" OR '
    'subject:"application to" OR subject:"applying to" OR subject:"application for" OR '
    'subject:"application with" OR subject:"application confirmation"'
)

# A Gmail search for emails that likely need a personal reply (interview
# scheduling, recruiter questions). Used by `drafts` to avoid spending LLM
# calls on confirmations/rejections that need no response.
REPLY_QUERY = (
    'subject:interview OR subject:availability OR subject:schedule OR '
    'subject:"next steps" OR subject:"speak with" OR subject:"chat" OR '
    'subject:"give us a call" OR subject:"your availability" OR '
    'subject:"set up a" OR subject:"book a" OR subject:"time to talk"'
)

# Where we keep secrets/state (created on demand, 0700).
APP_DIR = Path(os.path.expanduser("~")) / ".jobagent"
KEY_FILE = APP_DIR / "key"           # Fernet key, 0600
TOKEN_FILE = APP_DIR / "token.enc"   # encrypted OAuth credentials
CHANGES_LOG = APP_DIR / "changes.log"
SEEN_FILE = APP_DIR / "seen.json"            # ids already scanned by discover
DRAFTS_SEEN_FILE = APP_DIR / "drafts_seen.json"  # ids already considered for a reply

# From .env
CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secret.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()


def ensure_app_dir() -> None:
    """Create ~/.jobagent with private permissions if missing."""
    APP_DIR.mkdir(mode=0o700, exist_ok=True)
