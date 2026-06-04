"""Command-line interface for the Job Search Agent."""
import argparse
from pathlib import Path

from . import agent, auth, config, gmail_client, llm, scheduler, setup
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


def _require_gemini() -> bool:
    """Print a friendly message and return False if the Gemini key is missing."""
    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set. Add it to your .env "
              "(free key at https://aistudio.google.com/apikey), then retry.")
        return False
    return True


def _fetch(gmail, days, max_results, query=None):
    refs = gmail_client.list_recent(gmail, days=days, max_results=max_results, query=query)
    return refs, [gmail_client.parse_message(gmail_client.get_message(gmail, r["id"])) for r in refs]


def run_discover(gmail, tracker, days: int, max_fetch: int, max_llm: int) -> None:
    """Find new applications in Gmail and add them to the tracker."""
    refs, emails = _fetch(gmail, days, max_fetch, query=config.APPLICATION_QUERY)
    print(f"Found {len(refs)} likely application email(s) in the last {days} day(s); "
          f"reading up to {max_llm} with AI...")
    seen = agent.load_seen()
    summary = agent.discover_applications(tracker, emails, llm.extract_application,
                                          max_llm=max_llm, seen=seen,
                                          apply_keyword_filter=False)
    agent.save_seen(seen)
    for a in summary["added"]:
        print(f"  + added   {a}")
    for u in summary["updated"]:
        print(f"  ~ updated {u}")
    if not summary["added"] and not summary["updated"]:
        print("No new applications found.")
    if summary["skipped_quota"]:
        print(f"Note: {summary['skipped_quota']} application email(s) were not scanned "
              f"to stay under the Gemini free quota. They'll be picked up on the next run.")
    if summary.get("error"):
        print(f"Stopped early (likely hit the Gemini daily free quota): {summary['error']}")
        print("Anything found above is already saved. The rest continues tomorrow.")


def run_sync(gmail, tracker, days: int, max_fetch: int) -> None:
    """Scan recent Gmail and update statuses of already-tracked applications."""
    refs, emails = _fetch(gmail, days, max_fetch)
    print(f"Scanning {len(refs)} recent email(s) for status updates...")
    changes = agent.sync_inbox(tracker, emails, llm.classify_email)
    if not changes:
        print("No status changes.")
    else:
        print(f"Updated {len(changes)} application(s):")
        for c in changes:
            print(f"  • {c}")


def cmd_sync(args):
    if not _require_gemini():
        return
    run_sync(auth.gmail_service(), _tracker(), args.days, args.max)


def cmd_discover(args):
    if not _require_gemini():
        return
    run_discover(auth.gmail_service(), _tracker(), args.days, args.max, args.max_llm)


def cmd_update(args):
    """Daily workhorse: a single, memory-tracked scan that both adds new
    applications and advances existing statuses. Each email is read by the LLM
    at most once ever (seen.json), so repeated daily runs cost almost nothing."""
    if not _require_gemini():
        return
    run_discover(auth.gmail_service(), _tracker(), args.days, args.max, args.max_llm)


def cmd_schedule(args):
    if args.uninstall:
        removed = scheduler.uninstall()
        print("Removed the daily job." if removed else "No daily job was installed.")
        return
    try:
        path = scheduler.install(PROJECT_DIR, args.at)
    except Exception as exc:
        print(f"Could not install the daily job: {exc}")
        return
    print(f"Installed daily job at {args.at}. It runs `update` automatically each day.")
    print(f"  Logs:   {scheduler.LOG_PATH}")
    print(f"  Config: {path}")
    print("Remove anytime with:  python main.py schedule --uninstall")


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

    s = sub.add_parser("sync", help="(Optional/thorough) re-classify recent mail for status changes; uses more quota")
    s.add_argument("--days", type=int, default=2, help="How many days back to scan (default 2)")
    s.add_argument("--max", type=int, default=50, help="Max emails to fetch (default 50)")
    s.set_defaults(func=cmd_sync)

    d = sub.add_parser("discover", help="Find job applications in Gmail and add them to the tracker")
    d.add_argument("--days", type=int, default=7, help="How many days back to scan (default 7)")
    d.add_argument("--max", type=int, default=40, help="Max emails to fetch (default 40)")
    d.add_argument("--max-llm", type=int, default=15, dest="max_llm",
                   help="Max emails to scan with Gemini, protects the free quota (default 15)")
    d.set_defaults(func=cmd_discover)

    u = sub.add_parser("update", help="Daily: discover new applications + update statuses")
    u.add_argument("--days", type=int, default=7,
                   help="Discovery window in days; status-sync uses min(days,3). Default 7")
    u.add_argument("--max", type=int, default=40, help="Max emails to fetch (default 40)")
    u.add_argument("--max-llm", type=int, default=15, dest="max_llm",
                   help="Max emails to scan with Gemini (default 15)")
    u.set_defaults(func=cmd_update)

    sched = sub.add_parser("schedule", help="Install/remove the automatic daily run (macOS)")
    sched.add_argument("--at", default="09:00", help="Daily run time, HH:MM (default 09:00)")
    sched.add_argument("--uninstall", action="store_true", help="Remove the daily job")
    sched.set_defaults(func=cmd_schedule)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
