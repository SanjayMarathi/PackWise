"""HTTP endpoints of the assistant: streaming, guardrails and the transcript."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from assistant import agent
from assistant.models import Conversation

from .fakes import ScriptedAnthropic, message, text, tool

pytestmark = pytest.mark.django_db


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


@pytest.fixture
def scripted(monkeypatch, enabled):
    def install(*responses):
        fake = ScriptedAnthropic(*responses)
        monkeypatch.setattr(agent, "get_client", lambda: fake.client)
        return fake

    return install


def post_chat(api_client, **payload):
    return api_client.post("/api/assistant/chat/", payload, format="json")


def events_of(response):
    return [json.loads(line) for line in b"".join(response.streaming_content).decode().splitlines()]


def test_status_reports_configuration(api_client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert api_client.get("/api/assistant/status/").json() == {"enabled": False, "model": "claude-opus-5-5"}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert api_client.get("/api/assistant/status/").json()["enabled"] is True


def test_chat_is_unavailable_without_a_key(api_client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    response = post_chat(api_client, message="hi")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assistant_unavailable"


def test_chat_streams_ndjson_events(api_client, catalog, scripted):
    scripted(
        message(tool("recommend_box", {"items": [{"sku": "MOUSE", "quantity": 1}]}), stop_reason="tool_use"),
        message(text("Use the Small box.")),
    )
    response = post_chat(api_client, message="Pack a mouse")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/x-ndjson"
    events = events_of(response)
    assert events[0]["type"] == "conversation"
    assert events[-1] == {"type": "done"}
    assert [e["type"] for e in events[1:-1]] == ["status", "card", "text"]

    conversation_id = events[0]["id"]
    transcript = api_client.get(f"/api/assistant/conversations/{conversation_id}/").json()
    assert transcript["turns"] == 1
    assert [t["role"] for t in transcript["transcript"]] == ["user", "assistant"]
    assert transcript["transcript"][1]["text"] == "Use the Small box."
    assert transcript["transcript"][1]["cards"][0]["box_code"] == "SMALL"


def test_chat_accepts_the_browsers_ndjson_accept_header(api_client, catalog, scripted):
    """Regression: DRF's content negotiation used to answer 406 for Accept: application/x-ndjson."""
    scripted(message(text("ok")))
    response = api_client.post(
        "/api/assistant/chat/", {"message": "hi"}, format="json", HTTP_ACCEPT="application/x-ndjson, application/json"
    )
    assert response.status_code == 200
    assert events_of(response)[-1] == {"type": "done"}

    error = api_client.post("/api/assistant/chat/", {"message": ""}, format="json", HTTP_ACCEPT="application/x-ndjson")
    assert error.status_code == 400
    assert json.loads(error.content)["error"]["code"] == "validation_error"  # still a JSON envelope


def test_chat_continues_an_existing_conversation(api_client, catalog, scripted):
    fake = scripted(message(text("One.")), message(text("Two.")))
    first = events_of(post_chat(api_client, message="first"))
    conversation_id = first[0]["id"]
    second = events_of(post_chat(api_client, message="second", conversation_id=conversation_id))
    assert second[0]["id"] == conversation_id
    assert len(fake.requests[1]["body"]["messages"]) == 3  # user, assistant, user


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"message": ""}, "message"),
        ({}, "message"),
        ({"message": "x" * 2001}, "message"),
        ({"message": "hi", "role": "system"}, "role"),
    ],
)
def test_chat_validates_requests(api_client, enabled, payload, field):
    response = api_client.post("/api/assistant/chat/", payload, format="json")
    assert response.status_code == 400
    assert field in response.json()["error"]["details"]


def test_unknown_conversation_is_404(api_client, enabled):
    response = post_chat(api_client, message="hi", conversation_id="00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert api_client.get("/api/assistant/conversations/00000000-0000-0000-0000-000000000000/").status_code == 404


def test_busy_conversation_is_a_conflict(api_client, enabled):
    conversation = Conversation.objects.create(busy_since=timezone.now())
    response = post_chat(api_client, message="hi", conversation_id=str(conversation.pk))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversation_busy"


def test_stale_busy_flag_is_ignored(api_client, catalog, scripted):
    scripted(message(text("Back again.")))
    conversation = Conversation.objects.create(busy_since=timezone.now() - timedelta(minutes=10))
    assert post_chat(api_client, message="hi", conversation_id=str(conversation.pk)).status_code == 200


def test_full_conversation_is_a_conflict(api_client, enabled, settings):
    settings.PACKWISE_ASSISTANT = {**settings.PACKWISE_ASSISTANT, "MAX_TURNS": 2}
    conversation = Conversation.objects.create(turns=2)
    response = post_chat(api_client, message="hi", conversation_id=str(conversation.pk))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversation_full"


def test_chat_is_throttled(api_client, catalog, scripted, monkeypatch):
    from django.core.cache import cache
    from rest_framework.throttling import ScopedRateThrottle

    cache.clear()
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"assistant": "1/minute"})
    scripted(message(text("ok")))
    assert post_chat(api_client, message="one").status_code == 200
    throttled = post_chat(api_client, message="two")
    assert throttled.status_code == 429
    cache.clear()
