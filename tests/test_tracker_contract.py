from datetime import datetime, timedelta, timezone

from tests.fakes import FakeTracker


def test_add_and_find():
    t = FakeTracker()
    t.add_application("Acme", "QA Engineer", "LinkedIn")
    found = t.find_application("acme", "qa engineer")  # case-insensitive
    assert found is not None
    assert found.status == "Applied"


def test_update_status():
    t = FakeTracker()
    t.add_application("Acme", "QA Engineer", "LinkedIn")
    t.update_status("Acme", "QA Engineer", "Rejected", note="auto from email")
    assert t.find_application("Acme", "QA Engineer").status == "Rejected"


def test_get_filtered_by_status():
    t = FakeTracker()
    t.add_application("Acme", "QA", "LinkedIn")
    t.add_application("Beta", "SDET", "Referral")
    t.update_status("Beta", "SDET", "Offer")
    assert [a.company for a in t.get_applications(status="Offer")] == ["Beta"]


def test_get_filtered_since():
    t = FakeTracker()
    t.add_application("Old", "QA", "Web", date_applied="2000-01-01")
    t.add_application("New", "QA", "Web")
    since = datetime.now(timezone.utc) - timedelta(days=1)
    assert [a.company for a in t.get_applications(since=since)] == ["New"]
