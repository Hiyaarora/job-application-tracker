from jobagent import agent
from tests.fakes import FakeTracker


def _classifier(result):
    """Build a fake classifier that records which emails it was called on."""
    calls = []

    def classify(email, candidates):
        calls.append(email["id"])
        return result

    return classify, calls


HIGH = {
    "matched_company": "Acme", "matched_role": "QA Engineer",
    "intent": "interview_invite", "new_status": "Interview Scheduled",
    "confidence": 0.92,
}


def test_prefilter_only_passes_matching_emails_to_llm():
    t = FakeTracker()
    t.add_application("Acme", "QA Engineer", "LinkedIn")
    emails = [
        {"id": "1", "sender": "jobs@acmecorp.com", "sender_domain": "acmecorp.com",
         "subject": "Interview", "snippet": "", "body": "We'd like to meet you"},
        {"id": "2", "sender": "news@random.com", "sender_domain": "random.com",
         "subject": "Big sale", "snippet": "", "body": "buy now"},
    ]
    classify, calls = _classifier(HIGH)
    agent.sync_inbox(t, emails, classify, log_fn=lambda _m: None)
    assert calls == ["1"]  # email 2 was filtered out before any LLM call


def test_high_confidence_updates_status():
    t = FakeTracker()
    t.add_application("Acme", "QA Engineer", "LinkedIn")
    emails = [{"id": "1", "sender": "jobs@acme.com", "sender_domain": "acme.com",
               "subject": "Acme interview", "snippet": "", "body": "acme"}]
    classify, _ = _classifier(HIGH)
    changes = agent.sync_inbox(t, emails, classify, log_fn=lambda _m: None)
    assert t.find_application("Acme", "QA Engineer").status == "Interview Scheduled"
    assert len(changes) == 1


def test_low_confidence_does_not_update():
    t = FakeTracker()
    t.add_application("Acme", "QA Engineer", "LinkedIn")
    emails = [{"id": "1", "sender": "jobs@acme.com", "sender_domain": "acme.com",
               "subject": "Acme", "snippet": "", "body": "acme"}]
    low = {**HIGH, "intent": "rejection", "new_status": "Rejected", "confidence": 0.2}
    classify, _ = _classifier(low)
    changes = agent.sync_inbox(t, emails, classify, min_confidence=0.6,
                               log_fn=lambda _m: None)
    assert t.find_application("Acme", "QA Engineer").status == "Applied"
    assert changes == []


def test_no_status_change_intent_is_skipped():
    t = FakeTracker()
    t.add_application("Acme", "QA Engineer", "LinkedIn")
    emails = [{"id": "1", "sender": "jobs@acme.com", "sender_domain": "acme.com",
               "subject": "Acme follow up", "snippet": "", "body": "acme"}]
    followup = {**HIGH, "intent": "recruiter_followup", "new_status": None, "confidence": 0.9}
    classify, _ = _classifier(followup)
    changes = agent.sync_inbox(t, emails, classify, log_fn=lambda _m: None)
    assert t.find_application("Acme", "QA Engineer").status == "Applied"
    assert changes == []
