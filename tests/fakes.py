from datetime import datetime, timezone

from jobagent.tracker import Tracker, Application


class FakeTracker(Tracker):
    """In-memory Tracker for tests — no network."""

    def __init__(self):
        self._rows: list[Application] = []

    def add_application(self, company, role, source, date_applied=None, notes=""):
        now = datetime.now(timezone.utc)
        app = Application(
            company=company, role=role,
            date_applied=date_applied or now.date().isoformat(),
            source=source, status="Applied",
            last_updated=now.isoformat(timespec="seconds"), notes=notes,
        )
        self._rows.append(app)
        return app

    def update_status(self, company, role, status, note=None):
        app = self.find_application(company, role)
        if app is None:
            raise KeyError(f"{company}/{role} not found")
        app.status = status
        app.last_updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if note:
            app.notes = (app.notes + " | " + note).strip(" |")
        return app

    def get_applications(self, since=None, status=None):
        rows = self._rows
        if status:
            rows = [r for r in rows if r.status == status]
        if since:
            rows = [r for r in rows if r.date_applied >= since.date().isoformat()]
        return list(rows)

    def find_application(self, company, role):
        for r in self._rows:
            if r.company.lower() == company.lower() and r.role.lower() == role.lower():
                return r
        return None
