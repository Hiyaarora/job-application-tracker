"""Install a macOS launchd job that runs `update` once a day automatically.

launchd is macOS's native scheduler. We write a .plist into ~/Library/LaunchAgents
and load it; it runs whenever your Mac is awake at the chosen time (and catches up
on the next wake if the Mac was asleep).
"""
import subprocess
import sys
from pathlib import Path

from . import config

LABEL = "com.hiya.jobsearch-agent"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = config.APP_DIR / "daily.log"


def parse_time(text: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute), raising ValueError if out of range."""
    parts = text.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"Bad time {text!r}; use HH:MM, e.g. 09:00")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Time out of range: {text!r}")
    return hour, minute


def plist_content(label, python, main_py, project_dir, log_path, hour, minute) -> str:
    """Build the launchd plist XML that runs `python main.py update` daily."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{main_py}</string>
        <string>update</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{project_dir}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


def install(project_dir: Path, at: str) -> Path:
    """Write and load the daily launchd job. Returns the plist path."""
    hour, minute = parse_time(at)
    config.ensure_app_dir()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    xml = plist_content(
        label=LABEL, python=sys.executable,
        main_py=str(Path(project_dir) / "main.py"),
        project_dir=str(project_dir), log_path=str(LOG_PATH),
        hour=hour, minute=minute,
    )
    PLIST_PATH.write_text(xml)
    # Reload: unload first (ignore error if not loaded), then load.
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)],
                   capture_output=True, text=True)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)],
                   capture_output=True, text=True, check=True)
    return PLIST_PATH


def uninstall() -> bool:
    """Unload and delete the daily job. Returns True if it existed."""
    if not PLIST_PATH.exists():
        return False
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)],
                   capture_output=True, text=True)
    PLIST_PATH.unlink()
    return True
