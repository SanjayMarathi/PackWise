"""The Gemini loop end to end through the real google-genai SDK (scripted transport, real PostgreSQL)."""

import itertools

import pytest

from assistant import agent
from assistant.models import Conversation
from assistant.tools import TOOLS
from orders.models import Order

from .fakes_gemini import ScriptedGemini, call, text, turn

pytestmark = pytest.mark.django_db


def run(conversation, user_text, scripted):
    return list(agent.run_turn(conversation, user_text, client=scripted.client, provider="gemini"))


def of_type(events, kind):
    return [e for e in events if e["type"] == kind]


def test_full_turn_with_function_calls(catalog):
    scripted = ScriptedGemini(
        turn(call("list_products", {"search": "laptop"})),
        turn(call("recommend_box", {"items": [{"sku": "LAPTOP", "quantity": 2}]})),
        turn(text("Use the **Medium Flat** box."), text(" It costs ₹35.")),
    )
    conversation = Conversation.objects.create()
    events = run(conversation, "Pack 2 laptops", scripted)

    assert [e["text"] for e in of_type(events, "status")] == [
        "Looking up products…",
        "Packing the order in 3D against every box…",
    ]
    (card,) = [e["card"] for e in of_type(events, "card")]
    assert card["box_code"] == "MEDIUM-FLAT"
    assert "".join(e["text"] for e in of_type(events, "text")) == "Use the **Medium Flat** box. It costs ₹35."
    assert of_type(events, "error") == []
    assert Order.objects.get(pk=card["order_id"]).status == Order.Status.RECOMMENDED

    conversation.refresh_from_db()
    assert conversation.provider == "gemini"
    assert [m["role"] for m in conversation.messages] == ["user", "model", "user", "model", "user", "model"]
    assert conversation.transcript[-1]["cards"] == [card]


def test_function_responses_carry_call_ids_and_results(catalog):
    scripted = ScriptedGemini(turn(call("list_boxes", {}, id="call_boxes")), turn(text("Four boxes.")))
    run(Conversation.objects.create(), "Boxes?", scripted)
    (response_part,) = scripted.requests[1]["body"]["contents"][-1]["parts"]
    response = response_part["functionResponse"]
    assert response["id"] == "call_boxes"
    assert response["name"] == "list_boxes"
    assert [b["box_code"] for b in response["response"]["boxes"]] == ["SMALL", "MEDIUM", "MEDIUM-FLAT", "LARGE"]


def test_history_and_thought_signatures_are_replayed_verbatim(catalog):
    scripted = ScriptedGemini(
        turn(call("list_boxes", {})),
        turn(text("Four boxes.")),
        turn(text("Hello again.")),
    )
    conversation = Conversation.objects.create()
    run(conversation, "Boxes?", scripted)
    conversation.refresh_from_db()
    run(conversation, "Thanks", scripted)

    bodies = [r["body"] for r in scripted.requests]
    for earlier, later in itertools.pairwise(bodies):
        assert later["systemInstruction"] == earlier["systemInstruction"]
        assert later["tools"] == earlier["tools"]
        assert later["contents"][: len(earlier["contents"])] == earlier["contents"]
    model_turn = bodies[1]["contents"][1]
    assert model_turn["role"] == "model"
    assert "thoughtSignature" in model_turn["parts"][0]  # the function call's signature
    assert model_turn["parts"][-1].get("text", "") == "" and "thoughtSignature" in model_turn["parts"][-1]


def test_request_configuration(catalog, settings):
    settings.PACKWISE_ASSISTANT = {**settings.PACKWISE_ASSISTANT, "GEMINI_MODEL": "gemini-3.5-flash-lite"}
    scripted = ScriptedGemini(turn(text("Hi!")))
    run(Conversation.objects.create(), "Hello", scripted)
    request = scripted.requests[0]
    assert "/models/gemini-3.5-flash-lite:streamGenerateContent" in request["url"]
    body = request["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == agent.SYSTEM_PROMPT
    declarations = body["tools"][0]["functionDeclarations"]
    assert [d["name"] for d in declarations] == [t["name"] for t in TOOLS]
    assert declarations[2]["parameters_json_schema"] == TOOLS[2]["input_schema"]  # identical schemas for both providers
    assert body["generationConfig"]["thinkingConfig"]["thinking_level"] == "LOW"
    assert body["generationConfig"]["maxOutputTokens"] == settings.PACKWISE_ASSISTANT["MAX_TOKENS"]


def test_invalid_arguments_come_back_as_an_error_response(catalog):
    scripted = ScriptedGemini(
        turn(call("recommend_box", {"items": [{"sku": "UNICORN", "quantity": 1}]})),
        turn(text("I couldn't find that product.")),
    )
    events = run(Conversation.objects.create(), "Pack a unicorn", scripted)
    response = scripted.requests[1]["body"]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert "Unknown SKU(s): UNICORN" in response["error"]
    assert of_type(events, "card") == []
    assert not Order.objects.exists()


def test_safety_block_stops_without_running_tools(catalog):
    scripted = ScriptedGemini(turn(call("list_boxes", {}), finish="SAFETY"))
    events = run(Conversation.objects.create(), "something unsafe", scripted)
    assert "can't help" in "".join(e["text"] for e in of_type(events, "text"))
    assert len(scripted.requests) == 1


def test_call_cut_off_by_token_limit_is_never_executed(catalog):
    scripted = ScriptedGemini(
        turn(call("recommend_box", {"items": [{"sku": "LAPTOP", "quantity": 1}]}), finish="MAX_TOKENS")
    )
    conversation = Conversation.objects.create()
    events = run(conversation, "Pack a laptop", scripted)
    assert of_type(events, "error")
    assert not Order.objects.exists()
    conversation.refresh_from_db()
    assert [m["role"] for m in conversation.messages] == ["user"]


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(429, "free usage limit"), (403, "API key rejected"), (404, "model is not available"), (500, "having trouble")],
)
def test_api_errors_end_the_turn_cleanly(catalog, status, fragment):
    conversation = Conversation.objects.create()
    events = run(conversation, "Hello", ScriptedGemini(status))
    (error,) = of_type(events, "error")
    assert fragment in error["message"]
    conversation.refresh_from_db()
    assert conversation.busy_since is None
    assert conversation.messages[-1]["role"] == "user"


def test_error_after_a_tool_round_keeps_history_valid(catalog):
    scripted = ScriptedGemini(turn(call("list_boxes", {})), 500)
    conversation = Conversation.objects.create()
    run(conversation, "Boxes?", scripted)
    conversation.refresh_from_db()
    assert [m["role"] for m in conversation.messages] == ["user", "model", "user"]
    assert "function_response" in conversation.messages[-1]["parts"][0]


def test_round_limit(catalog, settings):
    settings.PACKWISE_ASSISTANT = {**settings.PACKWISE_ASSISTANT, "MAX_TOOL_ROUNDS": 2}
    scripted = ScriptedGemini(turn(call("list_boxes", {})), turn(call("list_boxes", {})))
    events = run(Conversation.objects.create(), "Loop", scripted)
    assert "too many steps" in of_type(events, "error")[0]["message"]


def test_empty_answer_is_reported(catalog):
    scripted = ScriptedGemini(
        [{"candidates": [{"content": {"role": "model", "parts": []}, "finishReason": "STOP", "index": 0}]}]
    )
    events = run(Conversation.objects.create(), "Hello", scripted)
    assert "empty answer" in of_type(events, "error")[0]["message"]


# ---------------------------------------------------------------- provider selection


@pytest.mark.parametrize(
    ("configured", "keys", "expected"),
    [
        ("auto", {}, None),
        ("auto", {"GEMINI_API_KEY": "g"}, "gemini"),
        ("auto", {"GOOGLE_API_KEY": "g"}, "gemini"),
        ("auto", {"ANTHROPIC_API_KEY": "a"}, "claude"),
        ("auto", {"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"}, "gemini"),  # free tier preferred
        ("claude", {"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"}, "claude"),
        ("claude", {"GEMINI_API_KEY": "g"}, None),
        ("gemini", {"ANTHROPIC_API_KEY": "a"}, None),
    ],
)
def test_provider_selection(settings, monkeypatch, configured, keys, expected):
    settings.PACKWISE_ASSISTANT = {**settings.PACKWISE_ASSISTANT, "PROVIDER": configured}
    for key, value in keys.items():
        monkeypatch.setenv(key, value)
    assert agent.assistant_provider() == expected
    assert agent.assistant_enabled() is (expected is not None)


def test_get_client_reads_the_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    client = agent.get_gemini_client()
    assert client._api_client.api_key == "from-env"
