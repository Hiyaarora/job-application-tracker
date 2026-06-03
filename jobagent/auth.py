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
