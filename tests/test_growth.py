from datetime import datetime, timedelta, timezone

from jobagent import agent, llm
from tests.fakes import FakeTracker


def _now():
    return datetime(2026, 6, 4, tzinfo=timezone.utc)


def test_weekly_summary_counts():
    t = FakeTracker()
    # 3 applied this week, 1 older
    t.add_application("A", "r", "Email")                       # Applied, today
    t.add_application("B", "r", "Email")
    t.update_status("B", "r", "Interview Scheduled")
    t.add_application("C", "r", "Email")
    t.update_status("C", "r", "Rejected")
    t.add_application("D", "r", "Email", date_applied="2026-01-01")  # old, Applied

    s = agent.weekly_summary(t, now=_now())
    assert s["total"] == 4
    assert s["responses"] == 2          # B (interview) + C (rejected) responded
    assert s["interviews"] == 1
    assert s["rejections"] == 1
    assert s["offers"] == 0
    assert s["pending"] == 2            # A and D still Applied
    assert s["response_rate"] == 0.5    # 2 / 4
    assert s["applied_this_week"] == 3  # A, B, C today; D is old


def test_weekly_summary_empty():
    s = agent.weekly_summary(FakeTracker(), now=_now())
    assert s["total"] == 0
    assert s["response_rate"] == 0.0


def test_daily_task_returns_text(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: "Read about metamorphic testing for ML models.")
    assert "metamorphic" in llm.daily_task()
