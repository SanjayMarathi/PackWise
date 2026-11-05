"""The agent loop, end to end through the real Anthropic SDK (scripted transport, real PostgreSQL)."""

import itertools
import json

import pytest

from assistant import agent
from assistant.models import Conversation
from assistant.tools import TOOLS
from orders.models import Order

from .fakes import ScriptedAnthropic, message, text, tool

pytestmark = pytest.mark.django_db


def run(conversation, user_text, scripted):
    return list(agent.run_turn(conversation, user_text, client=scripted.client))


def of_type(events, kind):
    return [e for e in events if e["type"] == kind]


def test_full_turn_finds_skus_recommends_and_answers(catalog):
    scripted = ScriptedAnthropic(
        message(tool("list_products", {"search": "laptop"}), stop_reason="tool_use"),
        message(tool("recommend_box", {"items": [{"sku": "laptop", "quantity": 2}]}), stop_reason="tool_use"),
        message(text("The **Medium Flat** box fits both laptops.")),
    )
    conversation = Conversation.objects.create()
    events = run(conversation, "Pack 2 laptops", scripted)

    assert [e["text"] for e in of_type(events, "status")] == [
        "Looking up products…",
        "Packing the order in 3D against every box…",
    ]
    (card,) = [e["card"] for e in of_type(events, "card")]
    assert card["kind"] == "recommendation"
    assert card["box_code"] == "MEDIUM-FLAT"
    assert card["status"] == "success"
    assert "".join(e["text"] for e in of_type(events, "text")).endswith("fits both laptops.")
    assert of_type(events, "error") == []

    order = Order.objects.get(pk=card["order_id"])
    assert order.status == Order.Status.RECOMMENDED
    assert [(i.product.sku, i.quantity) for i in order.items.all()] == [("LAPTOP", 2)]

    conversation.refresh_from_db()
    assert [m["role"] for m in conversation.messages] == ["user", "assistant", "user", "assistant", "user", "assistant"]
    assert conversation.turns == 1
    assert conversation.busy_since is None
    assert conversation.transcript[-1]["cards"] == [card]


def test_tool_results_reach_the_model(catalog):
    scripted = ScriptedAnthropic(
        message(tool("list_boxes", {}, id="toolu_boxes"), stop_reason="tool_use"),
        message(text("Done.")),
    )
    run(Conversation.objects.create(), "What boxes are there?", scripted)
    last_user = scripted.requests[1]["body"]["messages"][-1]
    (result,) = last_user["content"]
    assert result["tool_use_id"] == "toolu_boxes"
    assert result["is_error"] is False
    codes = [b["box_code"] for b in json.loads(result["content"])["boxes"]]
    assert codes == ["SMALL", "MEDIUM", "MEDIUM-FLAT", "LARGE"]  # active only, cheapest first


def test_history_is_append_only_and_replayed_verbatim(catalog):
    """Claude binds thinking blocks to the exact prefix, so every request must extend the last one."""
    scripted = ScriptedAnthropic(
        message(tool("list_boxes", {}), stop_reason="tool_use"),
        message(text("Four boxes.")),
        message(
            tool("check_box_fit", {"items": [{"sku": "MOUSE", "quantity": 1}], "box_code": "SMALL"}),
            stop_reason="tool_use",
        ),
        message(text("Yes, it fits.")),
    )
    conversation = Conversation.objects.create()
    run(conversation, "List boxes", scripted)
    conversation.refresh_from_db()
    run(conversation, "Does a mouse fit the small box?", scripted)

    bodies = [r["body"] for r in scripted.requests]
    for earlier, later in itertools.pairwise(bodies):
        assert later["system"] == earlier["system"]
        assert later["tools"] == earlier["tools"]
        assert later["messages"][: len(earlier["messages"])] == earlier["messages"]
    # Thinking blocks (with their signatures) are sent back unchanged.
    replayed = bodies[-1]["messages"][1]["content"][0]
    assert replayed == {"type": "thinking", "thinking": "", "signature": replayed["signature"]}
    assert replayed["signature"].startswith("sig-")


def test_request_parameters(catalog, settings):
    settings.PACKWISE_ASSISTANT = {**settings.PACKWISE_ASSISTANT, "EFFORT": "low"}
    scripted = ScriptedAnthropic(message(text("Hi!")))
    run(Conversation.objects.create(), "Hello", scripted)
    request = scripted.requests[0]
    body = request["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["stream"] is True
    assert body["fallbacks"] == "default"
    assert body["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    assert body["output_config"] == {"effort": "low"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in body["tools"]] == [t["name"] for t in TOOLS]
    assert all(t["eager_input_streaming"] is True for t in body["tools"])
    assert set(request["headers"]["anthropic-beta"].split(",")) == {
        "server-side-fallback-2026-07-01",
        "thinking-binding-controls-2026-08-01",
    }


def test_invalid_tool_input_is_returned_as_an_error_result(catalog):
    scripted = ScriptedAnthropic(
        message(tool("recommend_box", {"items": [{"sku": "UNICORN", "quantity": 1}]}), stop_reason="tool_use"),
        message(text("I couldn't find that product.")),
    )
    events = run(Conversation.objects.create(), "Pack a unicorn", scripted)
    result = scripted.requests[1]["body"]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "Unknown SKU(s): UNICORN" in result["content"]
    assert of_type(events, "card") == []
    assert not Order.objects.exists()


def test_refusal_stops_without_running_tools(catalog):
    scripted = ScriptedAnthropic(message(tool("list_boxes", {}), stop_reason="refusal"))
    events = run(Conversation.objects.create(), "something unsafe", scripted)
    assert "can't help" in "".join(e["text"] for e in of_type(events, "text"))
    assert len(scripted.requests) == 1


def test_truncated_tool_input_is_never_executed(catalog):
    scripted = ScriptedAnthropic(
        message(tool("recommend_box", {"items": [{"sku": "LAPTOP", "quantity": 1}]}), stop_reason="max_tokens")
    )
    conversation = Conversation.objects.create()
    events = run(conversation, "Pack a laptop", scripted)
    assert of_type(events, "error")
    assert not Order.objects.exists()
    conversation.refresh_from_db()
    assert [m["role"] for m in conversation.messages] == ["user"]  # no dangling tool_use


@pytest.mark.parametrize(("status", "fragment"), [(401, "not configured correctly"), (429, "busy"), (500, "error")])
def test_api_errors_end_the_turn_cleanly(catalog, status, fragment):
    conversation = Conversation.objects.create()
    events = run(conversation, "Hello", ScriptedAnthropic(status))
    (error,) = of_type(events, "error")
    assert fragment in error["message"]
    conversation.refresh_from_db()
    assert conversation.busy_since is None
    assert conversation.messages[-1]["role"] == "user"


def test_error_after_a_tool_round_keeps_history_valid(catalog):
    scripted = ScriptedAnthropic(message(tool("list_boxes", {}), stop_reason="tool_use"), 500)
    conversation = Conversation.objects.create()
    run(conversation, "Boxes?", scripted)
    conversation.refresh_from_db()
    # The completed round (tool call + its result) is kept; nothing is left unanswered.
    assert [m["role"] for m in conversation.messages] == ["user", "assistant", "user"]
    assert conversation.messages[-1]["content"][0]["type"] == "tool_result"


def test_tool_round_limit(catalog, settings):
    settings.PACKWISE_ASSISTANT = {**settings.PACKWISE_ASSISTANT, "MAX_TOOL_ROUNDS": 2}
    scripted = ScriptedAnthropic(
        message(tool("list_boxes", {}), stop_reason="tool_use"),
        message(tool("list_boxes", {}), stop_reason="tool_use"),
    )
    events = run(Conversation.objects.create(), "Loop forever", scripted)
    assert "too many steps" in of_type(events, "error")[0]["message"]
    assert len(scripted.requests) == 2


def test_encode_events_writes_ndjson():
    lines = (
        b"".join(agent.encode_events(iter([{"type": "text", "text": "₹35"}, {"type": "done"}]))).decode().splitlines()
    )
    assert [json.loads(line) for line in lines] == [{"type": "text", "text": "₹35"}, {"type": "done"}]
