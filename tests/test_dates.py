from datetime import datetime, timezone

import pytest

from jobagent.dates import parse_since


def test_parse_days():
    base = datetime(2026, 6, 3, tzinfo=timezone.utc)
    assert parse_since("30d", now=base).date().isoformat() == "2026-05-04"


def test_parse_weeks():
    base = datetime(2026, 6, 3, tzinfo=timezone.utc)
    assert parse_since("2w", now=base).date().isoformat() == "2026-05-20"


def test_parse_none_returns_none():
    assert parse_since(None) is None


def test_parse_bad_raises():
    with pytest.raises(ValueError):
        parse_since("banana")
