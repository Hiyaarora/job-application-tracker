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
SEEN_FILE = APP_DIR / "seen.json"    # ids of emails already scanned by discover

# From .env
CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "client_secret.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()


def ensure_app_dir() -> None:
    """Create ~/.jobagent with private permissions if missing."""
    APP_DIR.mkdir(mode=0o700, exist_ok=True)
