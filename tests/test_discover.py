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


def test_discover_without_keyword_filter_scans_all():
    # When Gmail already filtered (apply_keyword_filter=False), even an email
    # with no job keywords in its text should be scanned.
    t = FakeTracker()
    emails = [_email("1", subject="Postmanaut welcome", body="we're delighted")]
    calls = []

    def extractor(e):
        calls.append(e["id"])
        return {"is_job_application": True, "company": "Postman", "role": "SE",
                "status": "Applied", "confidence": 0.9}

    agent.discover_applications(t, emails, extractor, apply_keyword_filter=False,
                                log_fn=lambda _m: None)
    assert calls == ["1"]
    assert t.find_application("Postman", "SE") is not None


def test_discover_skips_already_seen_emails():
    t = FakeTracker()
    emails = [_email("1", subject="job interview", body="role at acme")]
    calls = []

    def extractor(e):
        calls.append(e["id"])
        return {"is_job_application": True, "company": "Acme", "role": "QA",
                "status": "Applied", "confidence": 0.9}

    seen = {"1"}
    summary = agent.discover_applications(t, emails, extractor, seen=seen,
                                          log_fn=lambda _m: None)
    assert calls == []                 # already-seen email not re-scanned
    assert summary["added"] == []


def test_discover_marks_scanned_emails_as_seen():
    t = FakeTracker()
    emails = [_email("1", subject="job interview", body="role at acme")]

    def extractor(e):
        return {"is_job_application": True, "company": "Acme", "role": "QA",
                "status": "Applied", "confidence": 0.9}

    seen = set()
    agent.discover_applications(t, emails, extractor, seen=seen, log_fn=lambda _m: None)
    assert "1" in seen                 # scanned id recorded so future runs skip it


def test_discover_skips_otp_noise_without_llm_call():
    t = FakeTracker()
    emails = [_email("1", subject="Your verification code is 123456",
                     body="one-time code for your application")]
    calls = []

    def extractor(e):
        calls.append(e["id"])
        return {"is_job_application": True, "company": "X", "role": "Y",
                "status": "Applied", "confidence": 0.9}

    agent.discover_applications(t, emails, extractor, apply_keyword_filter=False,
                                log_fn=lambda _m: None)
    assert calls == []            # OTP email never reached the LLM
    assert t.get_applications() == []


def test_discover_merges_three_company_emails_into_one_row():
    # GitLab: OTP (no role), confirmation (Applied), rejection (Rejected).
    t = FakeTracker()
    emails = [
        _email("otp", subject="Your verification code", body="otp for your application"),
        _email("conf", subject="Thank you for applying to GitLab", body="application received"),
        _email("rej", subject="Update on your GitLab application", body="not moving forward"),
    ]
    by_id = {
        "otp": {"is_job_application": True, "company": "GitLab", "role": None,
                "status": "Applied", "confidence": 0.8},
        "conf": {"is_job_application": True, "company": "GitLab", "role": "Backend Engineer",
                 "status": "Applied", "confidence": 0.9},
        "rej": {"is_job_application": True, "company": "GitLab", "role": "Backend Engineer",
                "status": "Rejected", "confidence": 0.95},
    }
    agent.discover_applications(t, emails, lambda e: by_id[e["id"]],
                               apply_keyword_filter=False, log_fn=lambda _m: None)
    apps = t.get_applications()
    assert len(apps) == 1                          # one GitLab row, not three
    assert apps[0].company == "GitLab"
    assert apps[0].role == "Backend Engineer"      # real role preferred over unknown
    assert apps[0].status == "Rejected"            # most-advanced status wins


def test_discover_uses_earliest_email_date_as_applied():
    t = FakeTracker()
    conf = _email("conf", subject="Thank you for applying to ClanX", body="received")
    conf["date"] = "2026-06-03"
    rej = _email("rej", subject="Update on your ClanX application", body="rejected")
    rej["date"] = "2026-06-06"
    by_id = {
        "conf": {"is_job_application": True, "company": "ClanX", "role": "AI Engineer",
                 "status": "Applied", "confidence": 0.9},
        "rej": {"is_job_application": True, "company": "ClanX", "role": "AI Engineer",
                "status": "Rejected", "confidence": 0.9},
    }
    agent.discover_applications(t, [rej, conf], lambda e: by_id[e["id"]],
                               apply_keyword_filter=False, log_fn=lambda _m: None)
    app = t.find_by_company("ClanX")
    assert app.date_applied == "2026-06-03"   # earliest email, not discovery date
    assert app.status == "Rejected"


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
