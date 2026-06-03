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
