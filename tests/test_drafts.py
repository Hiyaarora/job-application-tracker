from jobagent import agent


def _email(id, subject="", body="", sender="r@acme.com"):
    return {"id": id, "sender": sender, "sender_domain": "acme.com",
            "subject": subject, "snippet": "", "body": body, "thread_id": "t" + id}


def test_propose_drafts_selects_only_reply_needed():
    emails = [_email("1", subject="Interview availability"),
              _email("2", subject="Application received")]
    replies = {
        "1": {"needs_reply": True, "draft": "Happy to interview!"},
        "2": {"needs_reply": False, "draft": ""},
    }
    result = agent.propose_drafts(emails, lambda e: replies[e["id"]], seen=set())
    assert len(result["drafts"]) == 1
    assert result["drafts"][0]["email"]["id"] == "1"
    assert result["drafts"][0]["draft"] == "Happy to interview!"


def test_propose_drafts_skips_noise_and_seen():
    emails = [_email("otp", subject="Your verification code"),
              _email("done", subject="Interview availability")]
    calls = []

    def proposer(e):
        calls.append(e["id"])
        return {"needs_reply": True, "draft": "x"}

    result = agent.propose_drafts(emails, proposer, seen={"done"})
    assert calls == []                 # otp filtered (noise), done already seen
    assert result["drafts"] == []


def test_propose_drafts_marks_considered_as_seen():
    emails = [_email("1", subject="Interview")]
    seen = set()
    agent.propose_drafts(emails, lambda e: {"needs_reply": False, "draft": ""}, seen=seen)
    assert "1" in seen                 # won't be re-drafted next time


def test_review_draft_approve_edit_skip():
    assert agent.review_draft("orig", lambda _p: "a", lambda d: "EDITED") == "orig"
    assert agent.review_draft("orig", lambda _p: "s", lambda d: "EDITED") is None
    assert agent.review_draft("orig", lambda _p: "e", lambda d: "EDITED") == "EDITED"
