from unittest.mock import MagicMock

from jobagent.tracker import get_or_create_sheet


def test_creates_sheet_when_no_id():
    service = MagicMock()
    create = service.spreadsheets.return_value.create.return_value
    create.execute.return_value = {"spreadsheetId": "new123"}
    values = service.spreadsheets.return_value.values.return_value
    values.update.return_value.execute.return_value = {}

    sid = get_or_create_sheet(service, "")
    assert sid == "new123"
    values.update.assert_called_once()  # header row written


def test_returns_existing_id():
    service = MagicMock()
    assert get_or_create_sheet(service, "existing") == "existing"
    service.spreadsheets.return_value.create.assert_not_called()
