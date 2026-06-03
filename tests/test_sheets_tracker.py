from unittest.mock import MagicMock

from jobagent.tracker import SheetsTracker


def _mock_service(rows):
    """Build a fake Sheets service whose values().get() returns `rows`."""
    service = MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {"values": rows}
    values.append.return_value.execute.return_value = {}
    values.update.return_value.execute.return_value = {}
    return service


HEADER = ["Company", "Role", "Date Applied", "Source", "Status", "Last Updated", "Notes"]


def test_get_applications_parses_rows():
    rows = [
        HEADER,
        ["Acme", "QA", "2026-06-01", "LinkedIn", "Applied", "2026-06-01T10:00:00", ""],
    ]
    t = SheetsTracker(_mock_service(rows), spreadsheet_id="sheet123")
    apps = t.get_applications()
    assert len(apps) == 1
    assert apps[0].company == "Acme"


def test_add_application_appends_row():
    t = SheetsTracker(_mock_service([HEADER]), spreadsheet_id="sheet123")
    app = t.add_application("Beta", "SDET", "Referral")
    assert app.status == "Applied"
    t.service.spreadsheets.return_value.values.return_value.append.assert_called_once()


def test_update_status_writes_row():
    rows = [
        HEADER,
        ["Acme", "QA", "2026-06-01", "LinkedIn", "Applied", "2026-06-01T10:00:00", ""],
    ]
    t = SheetsTracker(_mock_service(rows), spreadsheet_id="sheet123")
    app = t.update_status("Acme", "QA", "Rejected", note="email")
    assert app.status == "Rejected"
    t.service.spreadsheets.return_value.values.return_value.update.assert_called_once()
