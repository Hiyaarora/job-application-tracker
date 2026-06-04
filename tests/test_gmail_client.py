import base64
from unittest.mock import MagicMock

from jobagent import gmail_client


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_list_recent_uses_newer_than_query():
    service = MagicMock()
    msgs = service.users.return_value.messages.return_value
    msgs.list.return_value.execute.return_value = {
        "messages": [{"id": "a", "threadId": "t1"}, {"id": "b", "threadId": "t2"}]
    }
    ids = gmail_client.list_recent(service, days=2, max_results=50)
    assert ids == [{"id": "a", "threadId": "t1"}, {"id": "b", "threadId": "t2"}]
    _, kwargs = msgs.list.call_args
    assert kwargs["q"] == "newer_than:2d"
    assert kwargs["maxResults"] == 50


def test_list_recent_appends_query():
    service = MagicMock()
    msgs = service.users.return_value.messages.return_value
    msgs.list.return_value.execute.return_value = {"messages": []}
    gmail_client.list_recent(service, days=7, query="from:greenhouse.io")
    _, kwargs = msgs.list.call_args
    assert kwargs["q"] == "newer_than:7d (from:greenhouse.io)"


def test_list_recent_handles_no_messages():
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {}
    assert gmail_client.list_recent(service) == []


def test_parse_message_extracts_fields_and_plain_body():
    msg = {
        "id": "a",
        "threadId": "t1",
        "payload": {
            "headers": [
                {"name": "From", "value": "Recruiter <jobs@acmecorp.com>"},
                {"name": "Subject", "value": "Your application"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Hello there")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>ignore</p>")}},
            ],
        },
        "snippet": "Hello there...",
    }
    parsed = gmail_client.parse_message(msg)
    assert parsed["sender"] == "Recruiter <jobs@acmecorp.com>"
    assert parsed["sender_domain"] == "acmecorp.com"
    assert parsed["subject"] == "Your application"
    assert "Hello there" in parsed["body"]
    assert parsed["thread_id"] == "t1"


def test_parse_message_body_in_payload_root():
    msg = {
        "id": "x",
        "threadId": "tx",
        "payload": {
            "headers": [{"name": "From", "value": "a@b.com"}],
            "mimeType": "text/plain",
            "body": {"data": _b64("Root body")},
        },
        "snippet": "Root body",
    }
    parsed = gmail_client.parse_message(msg)
    assert parsed["body"] == "Root body"
    assert parsed["sender_domain"] == "b.com"


def test_sender_email_extracts_address():
    assert gmail_client.sender_email("Recruiter <jobs@acme.com>") == "jobs@acme.com"
    assert gmail_client.sender_email("plain@beta.com") == "plain@beta.com"
    assert gmail_client.sender_email("No address here") == ""


def test_send_message_calls_api():
    service = MagicMock()
    send = service.users.return_value.messages.return_value.send
    send.return_value.execute.return_value = {"id": "sent1"}
    result = gmail_client.send_message(service, "to@x.com", "Hi", "Body text")
    assert result == {"id": "sent1"}
    send.assert_called_once()
