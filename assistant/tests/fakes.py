"""A real ``anthropic.Anthropic`` client whose HTTP transport replays scripted responses.

Using the real SDK over a mock transport exercises the real stream parser, event
types and request serialization, with no network and no API key.
"""

from __future__ import annotations

import itertools
import json

import anthropic
import httpx2

_ids = itertools.count(1)


def _sse(events: list[dict]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def message(*blocks: dict, stop_reason: str = "end_turn") -> list[dict]:
    """SSE events for one assistant message. Every message starts with a signed thinking block."""
    n = next(_ids)
    events = [
        {
            "type": "message_start",
            "message": {
                "id": f"msg_{n}",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 1},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": f"sig-{n}"}},
        {"type": "content_block_stop", "index": 0},
    ]
    for index, block in enumerate(blocks, start=1):
        if block["type"] == "text":
            events += [
                {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": block["text"]}},
                {"type": "content_block_stop", "index": index},
            ]
        else:
            events += [
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}},
                },
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])},
                },
                {"type": "content_block_stop", "index": index},
            ]
    events += [
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 50},
        },
        {"type": "message_stop"},
    ]
    return events


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def tool(name: str, input: dict, id: str | None = None) -> dict:
    return {"type": "tool_use", "id": id or f"toolu_{next(_ids)}", "name": name, "input": input}


class ScriptedAnthropic:
    """Each request pops the next scripted response: a list of SSE events, or an HTTP status code."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.client = anthropic.Anthropic(
            api_key="test-key",
            max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(self._handle)),
        )

    def _handle(self, request):
        self.requests.append({"body": json.loads(request.content), "headers": dict(request.headers)})
        if not self.responses:
            raise AssertionError("The agent made more API calls than the test scripted.")
        spec = self.responses.pop(0)
        if isinstance(spec, int):
            kind = {401: "authentication_error", 429: "rate_limit_error"}.get(spec, "api_error")
            return httpx2.Response(spec, json={"type": "error", "error": {"type": kind, "message": "scripted"}})
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_sse(spec))
