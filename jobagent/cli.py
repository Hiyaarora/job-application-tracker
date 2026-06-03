"""Command-line interface for the Job Search Agent."""
import argparse
from pathlib import Path

from . import auth, config, setup
from .dates import parse_since
from .tracker import SheetsTracker, get_or_create_sheet

# Project root = the folder containing main.py (one level above this package).
PROJECT_DIR = Path(__file__).resolve().parent.parent


def _tracker() -> SheetsTracker:
    """Build a SheetsTracker, auto-creating the sheet on first run."""
    service = auth.sheets_service()
    sid = get_or_create_sheet(service, config.SPREADSHEET_ID)
    if sid != config.SPREADSHEET_ID:
        print(f"Created a new sheet. Add this to your .env:\n  SPREADSHEET_ID={sid}")
    return SheetsTracker(service, sid)


def cmd_setup(args):
    setup.run_setup(PROJECT_DIR)


def cmd_login(args):
    auth.login()
    print("Login successful. Encrypted token stored in ~/.jobagent/")


def cmd_add(args):
    app = _tracker().add_application(
        args.company, args.role, args.source, notes=args.notes or ""
    )
    print(f"Added: {app.company} — {app.role} [{app.status}]")


def cmd_list(args):
    since = parse_since(args.since)
    apps = _tracker().get_applications(since=since, status=args.status)
    if not apps:
        print("No applications found.")
        return
    for a in apps:
        print(f"{a.date_applied}  {a.company:20} {a.role:25} {a.status:20} {a.notes}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobagent", description="AI Job Search Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Guided first-time setup (opens Google pages)").set_defaults(func=cmd_setup)
    sub.add_parser("login", help="Authenticate with Google").set_defaults(func=cmd_login)

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

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
