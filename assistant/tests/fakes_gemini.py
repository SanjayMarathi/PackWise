"""A real ``google.genai.Client`` whose HTTP transport replays scripted streaming responses."""

from __future__ import annotations

import base64
import itertools
import json

import httpx
from google import genai
from google.genai import types

_ids = itertools.count(1)


def text(value: str) -> dict:
    return {"text": value}


def call(name: str, args: dict, id: str | None = None) -> dict:
    n = next(_ids)
    signature = base64.b64encode(f"sig-{n}".encode()).decode()
    return {"functionCall": {"id": id or f"call_{n}", "name": name, "args": args}, "thoughtSignature": signature}


def turn(*parts: dict, finish: str = "STOP") -> list[dict]:
    """Streamed chunks for one model turn: one part per chunk, then a signature-only closing chunk."""
    chunks = [{"candidates": [{"content": {"role": "model", "parts": [p]}, "index": 0}]} for p in parts]
    closing = base64.b64encode(f"end-{next(_ids)}".encode()).decode()
    chunks.append(
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "", "thoughtSignature": closing}]},
                    "finishReason": finish,
                    "index": 0,
                }
            ],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 5},
            "modelVersion": "gemini-3.6-flash",
        }
    )
    return chunks


class ScriptedGemini:
    """Each request pops the next scripted turn (a list of chunks) or an HTTP status code."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        transport = httpx.MockTransport(self._handle)
        self.client = genai.Client(
            api_key="test-key", http_options=types.HttpOptions(httpx_client=httpx.Client(transport=transport))
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append({"url": str(request.url), "body": json.loads(request.content)})
        if not self.responses:
            raise AssertionError("The agent made more API calls than the test scripted.")
        spec = self.responses.pop(0)
        if isinstance(spec, int):
            status = {429: "RESOURCE_EXHAUSTED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND"}.get(spec, "INTERNAL")
            return httpx.Response(spec, json={"error": {"code": spec, "message": "scripted", "status": status}})
        body = "".join(f"data: {json.dumps(chunk)}\r\n\r\n" for chunk in spec).encode()
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
