"""Interactive setup wizard: `python main.py setup`.

Walks a new user through Google Cloud + Gemini configuration, opening the right
pages in their browser and waiting at each step — so nobody has to hunt through
docs to get the agent running.
"""
import shutil
import webbrowser
from pathlib import Path

from . import auth, config

# Direct deep-links so the user lands exactly where they need to be.
URL_NEW_PROJECT = "https://console.cloud.google.com/projectcreate"
URL_ENABLE_GMAIL = "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
URL_ENABLE_SHEETS = "https://console.cloud.google.com/apis/library/sheets.googleapis.com"
URL_CONSENT = "https://console.cloud.google.com/apis/credentials/consent"
URL_CREDENTIALS = "https://console.cloud.google.com/apis/credentials"
URL_GEMINI_KEY = "https://aistudio.google.com/apikey"


# --------------------------------------------------------------------------- #
# Pure, testable helpers
# --------------------------------------------------------------------------- #
def ensure_env_file(env_path: Path, example_path: Path) -> bool:
    """Create .env from .env.example if it doesn't exist. Return True if created."""
    if env_path.exists():
        return False
    shutil.copyfile(example_path, env_path)
    return True


def set_env_var(env_path: Path, key: str, value: str) -> None:
    """Set KEY=value in a .env file, updating in place or appending. Keeps comments."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    out, found = [], False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n")


# --------------------------------------------------------------------------- #
# Interactive wizard
# --------------------------------------------------------------------------- #
def run_setup(project_dir: Path, *, opener=webbrowser.open, prompt=input, out=print) -> None:
    """Guide the user through setup. I/O is injectable so the flow can be tested."""
    env_path = project_dir / ".env"
    example_path = project_dir / ".env.example"
    secrets_path = project_dir / config.CLIENT_SECRETS_FILE

    def step(n, title):
        out("")
        out(f"── Step {n}: {title} " + "─" * max(0, 40 - len(title)))

    def open_and_wait(url, instruction):
        out(f"Opening: {url}")
        try:
            opener(url)
        except Exception:
            out("(Could not open a browser automatically — copy the link above.)")
        out(instruction)
        prompt("Press Enter when done... ")

    out("=" * 60)
    out("  Job Search Agent — guided setup")
    out("=" * 60)
    out("This wizard opens each Google page you need and waits for you.")

    # 1. Project
    step(1, "Create a Google Cloud project")
    open_and_wait(
        URL_NEW_PROJECT,
        "Create a project (e.g. 'Job Search Agent') and select it.",
    )

    # 2. Enable APIs
    step(2, "Enable the Gmail & Sheets APIs")
    open_and_wait(URL_ENABLE_GMAIL, "Click ENABLE on the Gmail API page.")
    open_and_wait(URL_ENABLE_SHEETS, "Click ENABLE on the Google Sheets API page.")

    # 3. Consent screen
    step(3, "Configure the OAuth consent screen")
    open_and_wait(
        URL_CONSENT,
        "Choose User Type = EXTERNAL, fill the app name + your email, then on the\n"
        "  'Test users' step add the Google account you'll log in with.",
    )

    # 4. OAuth credentials
    step(4, "Create Desktop-app OAuth credentials")
    out(f"Save the downloaded JSON as:\n  {secrets_path}")
    while True:
        open_and_wait(
            URL_CREDENTIALS,
            "Create Credentials → OAuth client ID → Application type 'Desktop app'\n"
            f"  → Create → DOWNLOAD JSON → save it as '{config.CLIENT_SECRETS_FILE}' in the project folder.",
        )
        if secrets_path.exists():
            out(f"Found {config.CLIENT_SECRETS_FILE}. ✓")
            break
        retry = prompt(f"Couldn't find {secrets_path}. Try again? [Y/n] ").strip().lower()
        if retry == "n":
            out("Skipping — you'll need that file before `login` works.")
            break

    # 5. .env
    step(5, "Create your .env file")
    if ensure_env_file(env_path, example_path):
        out(f"Created {env_path} from the template.")
    else:
        out(f"{env_path} already exists — leaving it as is.")

    # 6. Gemini key (optional now; needed for sync/drafts/task)
    step(6, "Gemini API key (free tier) — optional for now")
    out("Used later for reading emails and drafting replies. You can skip and add it later.")
    want = prompt("Set up the Gemini key now? [y/N] ").strip().lower()
    if want == "y":
        open_and_wait(URL_GEMINI_KEY, "Click 'Create API key' and copy it.")
        key = prompt("Paste your Gemini API key (or leave blank to skip): ").strip()
        if key:
            set_env_var(env_path, "GEMINI_API_KEY", key)
            out("Saved GEMINI_API_KEY to .env. ✓")

    # 7. Login
    step(7, "Log in to Google")
    if secrets_path.exists():
        do_login = prompt("Run the Google login now? [Y/n] ").strip().lower()
        if do_login != "n":
            auth.login()
            out("Login successful. Encrypted token stored in ~/.jobagent/ ✓")
    else:
        out(f"Skipping login — {config.CLIENT_SECRETS_FILE} is missing.")

    # Done
    out("")
    out("=" * 60)
    out("  Setup complete! Try:")
    out('    python main.py add --company Acme --role "QA Engineer" --source LinkedIn')
    out("    python main.py list --since 30d")
    out("=" * 60)
