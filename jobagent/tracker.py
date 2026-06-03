"""Storage abstraction. Agent logic depends on Tracker, never on Sheets directly."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config


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
