import pytest

from jobagent import llm, config


def test_classify_parses_json_and_maps_status(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: (
        '{"matched_company": "Acme", "matched_role": "QA Engineer", '
        '"intent": "interview_invite", "confidence": 0.92}'
    ))
    email = {"sender": "jobs@acme.com", "subject": "Interview", "body": "Let's chat"}
    result = llm.classify_email(email, candidates=[("Acme", "QA Engineer")])
    assert result["matched_company"] == "Acme"
    assert result["intent"] == "interview_invite"
    assert result["new_status"] == "Interview Scheduled"   # mapped in Python
    assert result["confidence"] == 0.92


def test_classify_strips_code_fences(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: (
        '```json\n{"matched_company": "Beta", "matched_role": "SDET", '
        '"intent": "rejection", "confidence": 0.8}\n```'
    ))
    result = llm.classify_email({"sender": "", "subject": "", "body": ""},
                                candidates=[("Beta", "SDET")])
    assert result["intent"] == "rejection"
    assert result["new_status"] == "Rejected"


def test_classify_handles_garbage_response(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: "I am not JSON at all")
    result = llm.classify_email({"sender": "", "subject": "", "body": ""},
                                candidates=[("Acme", "QA")])
    assert result["intent"] == "other"
    assert result["new_status"] is None
    assert result["confidence"] == 0.0


def test_model_requires_api_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm._model()


def test_extract_application_parses_and_validates(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: (
        '{"is_job_application": true, "company": "Acme", "role": "QA Engineer", '
        '"status": "Interview Scheduled", "confidence": 0.9}'
    ))
    result = llm.extract_application({"sender": "jobs@acme.com", "subject": "Interview", "body": ""})
    assert result["is_job_application"] is True
    assert result["company"] == "Acme"
    assert result["status"] == "Interview Scheduled"


def test_extract_application_defaults_bad_status_to_applied(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: (
        '{"is_job_application": true, "company": "Beta", "role": "SDET", '
        '"status": "Banana", "confidence": 0.7}'
    ))
    result = llm.extract_application({"sender": "", "subject": "", "body": ""})
    assert result["status"] == "Applied"


def test_extract_application_handles_garbage(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: "not json")
    result = llm.extract_application({"sender": "", "subject": "", "body": ""})
    assert result["is_job_application"] is False


def test_propose_reply_parses_needs_reply_and_draft(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: (
        '{"needs_reply": true, "draft": "Hi Sarah, I would be glad to interview..."}'
    ))
    r = llm.propose_reply({"sender": "r@acme.com", "subject": "Interview?", "body": "When are you free?"})
    assert r["needs_reply"] is True
    assert r["draft"].startswith("Hi Sarah")


def test_propose_reply_no_reply_needed(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: '{"needs_reply": false, "draft": ""}')
    r = llm.propose_reply({"sender": "", "subject": "Rejection", "body": "no"})
    assert r["needs_reply"] is False


def test_propose_reply_handles_garbage(monkeypatch):
    monkeypatch.setattr(llm, "_generate", lambda prompt: "not json")
    r = llm.propose_reply({"sender": "", "subject": "", "body": ""})
    assert r["needs_reply"] is False
    assert r["draft"] == ""


def test_is_retryable_detects_transient_errors():
    assert llm._is_retryable(Exception("429 You exceeded your current quota")) is True
    assert llm._is_retryable(Exception("Quota exceeded for metric")) is True
    assert llm._is_retryable(Exception("504 Deadline Exceeded")) is True
    assert llm._is_retryable(Exception("503 Service Unavailable")) is True
    assert llm._is_retryable(Exception("The read operation timed out")) is True
    assert llm._is_retryable(ValueError("bad json")) is False


def test_call_with_retry_retries_on_quota_then_succeeds():
    attempts = {"n": 0}
    slept = []

    def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Exception("429 quota exceeded")
        return "ok"

    result = llm._call_with_retry(fn, max_retries=3, sleep_fn=slept.append, base_delay=40)
    assert result == "ok"
    assert attempts["n"] == 3
    assert slept == [40, 40]   # slept before each of the 2 retries


def test_call_with_retry_gives_up_after_max():
    def fn():
        raise Exception("429 quota exceeded")

    slept = []
    try:
        llm._call_with_retry(fn, max_retries=2, sleep_fn=slept.append, base_delay=40)
        assert False, "should have raised"
    except Exception as e:
        assert "quota" in str(e).lower()
    assert len(slept) == 2


def test_call_with_retry_reraises_non_quota_immediately():
    def fn():
        raise ValueError("some other error")

    slept = []
    try:
        llm._call_with_retry(fn, max_retries=3, sleep_fn=slept.append)
        assert False
    except ValueError:
        pass
    assert slept == []   # no retry for non-quota errors
