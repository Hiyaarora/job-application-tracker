from jobagent import agent
from tests.fakes import FakeTracker


def _email(id, subject="", body="", sender="x@co.com"):
    return {"id": id, "sender": sender, "sender_domain": "co.com",
            "subject": subject, "snippet": "", "body": body}


def test_discover_prefilters_non_job_emails():
    t = FakeTracker()
    emails = [_email("1", subject="50% off shoes", body="big sale today")]
    calls = []

    def extractor(e):
        calls.append(e["id"])
        return {"is_job_application": True, "company": "X", "role": "Y",
                "status": "Applied", "confidence": 0.9}

    summary = agent.discover_applications(t, emails, extractor, log_fn=lambda _m: None)
    assert calls == []                 # keyword pre-filter dropped it before LLM
    assert summary["added"] == []


def test_discover_adds_new_application_with_status():
    t = FakeTracker()
    emails = [_email("1", subject="Your application to Acme",
                     body="Thank you for applying. We'd like to schedule an interview.")]

    def extractor(e):
        return {"is_job_application": True, "company": "Acme", "role": "QA Engineer",
                "status": "Interview Scheduled", "confidence": 0.9}

    summary = agent.discover_applications(t, emails, extractor, log_fn=lambda _m: None)
    app = t.find_application("Acme", "QA Engineer")
    assert app is not None
    assert app.status == "Interview Scheduled"
    assert len(summary["added"]) == 1


def test_discover_dedup_keeps_most_advanced_status():
    t = FakeTracker()
    emails = [
        _email("1", subject="application received", body="acme applied"),
        _email("2", subject="interview at acme", body="acme interview"),
    ]
    by_id = {
        "1": {"is_job_application": True, "company": "Acme", "role": "QA",
              "status": "Applied", "confidence": 0.9},
        "2": {"is_job_application": True, "company": "Acme", "role": "QA",
              "status": "Interview Scheduled", "confidence": 0.9},
    }
    summary = agent.discover_applications(t, emails, lambda e: by_id[e["id"]],
                                          log_fn=lambda _m: None)
    apps = t.get_applications()
    assert len(apps) == 1                       # deduped to one row
    assert apps[0].status == "Interview Scheduled"
    assert len(summary["added"]) == 1


def test_discover_respects_max_llm_cap():
    t = FakeTracker()
    emails = [_email(str(i), subject="job application interview", body="role") for i in range(5)]
    calls = []

    def extractor(e):
        calls.append(e["id"])
        return {"is_job_application": False, "company": None, "role": None,
                "status": "Applied", "confidence": 0.0}

    summary = agent.discover_applications(t, emails, extractor, max_llm=2,
                                          log_fn=lambda _m: None)
    assert len(calls) == 2
    assert summary["skipped_quota"] == 3
