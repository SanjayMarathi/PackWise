"""Gemini implementation of the assistant loop (``google-genai`` SDK).

Same tools, events and guardrails as the Claude loop in ``agent.py``. Gemini
attaches *thought signatures* to the parts it returns. Every model turn is
stored exactly as received (parts in order, signatures included, nothing
merged) and resent verbatim, which is what function calling with thinking
models requires.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
from django.conf import settings
from google import genai
from google.genai import errors, types

from .agent import SYSTEM_PROMPT, add_card, add_text, persist, separate_rounds
from .models import Conversation
from .tools import TOOL_LABELS, TOOLS, run_tool

logger = logging.getLogger("packwise.assistant")

# Finish reasons that mean "the model declined / was blocked", as opposed to a normal stop.
BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}


# Free-tier Gemini returns transient 503s ("unavailable") under load: retry those with backoff.
# 429 is deliberately excluded: on the free tier it means a quota was hit, and an immediate
# retry won't help, so the user gets the clear "usage limit" message straight away.
RETRY = types.HttpRetryOptions(
    attempts=4, initial_delay=1.0, max_delay=8.0, http_status_codes=[408, 500, 502, 503, 504]
)


def get_client(http_client: httpx.Client | None = None) -> genai.Client:
    # Reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the environment. Timeout is in milliseconds.
    # Retries also cover streamed calls: the SDK retries the initial response before streaming.
    return genai.Client(http_options=types.HttpOptions(timeout=120_000, retry_options=RETRY, httpx_client=http_client))


def function_declarations() -> list[types.FunctionDeclaration]:
    # The same frozen JSON Schemas the Claude tools use, so both providers see identical tools.
    return [
        types.FunctionDeclaration(
            name=t["name"], description=t["description"], parameters_json_schema=t["input_schema"]
        )
        for t in TOOLS
    ]


def _config() -> types.GenerateContentConfig:
    cfg = settings.PACKWISE_ASSISTANT
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[types.Tool(function_declarations=function_declarations())],
        # We run the tools ourselves: they write to the database and stream progress to the UI.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        thinking_config=types.ThinkingConfig(thinking_level=cfg["GEMINI_THINKING"]),
        max_output_tokens=cfg["MAX_TOKENS"],
    )


def _dump(content: types.Content) -> dict:
    return content.model_dump(mode="json", exclude_none=True)


def _is_empty(part: types.Part) -> bool:
    return not (part.text or part.function_call or part.thought_signature or part.function_response)


def _finish_name(reason: Any) -> str | None:
    if reason is None:
        return None
    return getattr(reason, "value", None) or getattr(reason, "name", None) or str(reason)


def run_rounds(conversation: Conversation, user_text: str, client: genai.Client, entry: dict) -> Iterator[dict]:
    cfg = settings.PACKWISE_ASSISTANT
    stored: list[dict] = list(conversation.messages)
    contents = [types.Content.model_validate(message) for message in stored]
    user = types.Content(role="user", parts=[types.Part(text=user_text)])
    contents.append(user)
    stored.append(_dump(user))
    persist(conversation, stored)
    config = _config()
    try:
        for _round in range(cfg["MAX_TOOL_ROUNDS"]):
            parts: list[types.Part] = []
            finish = None
            usage = None
            for chunk in client.models.generate_content_stream(
                model=cfg["GEMINI_MODEL"], contents=contents, config=config
            ):
                usage = chunk.usage_metadata or usage
                if not chunk.candidates:
                    feedback = chunk.prompt_feedback
                    if feedback and feedback.block_reason:
                        finish = "SAFETY"
                    continue
                candidate = chunk.candidates[0]
                finish = _finish_name(candidate.finish_reason) or finish
                for part in candidate.content.parts if candidate.content and candidate.content.parts else []:
                    parts.append(part)
                    if part.function_call:
                        yield {"type": "status", "text": TOOL_LABELS.get(part.function_call.name, "Working…")}
                    elif part.text and not part.thought:
                        yield add_text(entry, part.text)
            _log_usage(conversation, cfg["GEMINI_MODEL"], finish, usage)

            kept = [p for p in parts if not _is_empty(p)]
            calls = [p.function_call for p in kept if p.function_call]
            if finish in BLOCKED:
                if not entry["text"]:
                    yield add_text(entry, "Sorry, I can't help with that request.")
                break
            if not kept:
                if not entry["text"]:
                    yield {"type": "error", "message": "The assistant returned an empty answer. Please rephrase."}
                break
            model_turn = types.Content(role="model", parts=kept)
            if calls and finish == "MAX_TOKENS":
                # A tool call cut off by the token limit may carry truncated arguments; never run it.
                yield {"type": "error", "message": "The answer got too long. Please ask a narrower question."}
                break
            contents.append(model_turn)
            stored.append(_dump(model_turn))
            if not calls:
                persist(conversation, stored)
                break  # the answer is complete

            responses = []
            for call in calls:
                outcome = run_tool(call.name, dict(call.args or {}))
                result = json.loads(outcome.content)
                responses.append(
                    types.Part(function_response=types.FunctionResponse(id=call.id, name=call.name, response=result))
                )
                if outcome.card:
                    yield add_card(entry, outcome.card)
            # All results for one model turn go back together, in call order.
            tool_turn = types.Content(role="user", parts=responses)
            contents.append(tool_turn)
            stored.append(_dump(tool_turn))
            persist(conversation, stored)
            yield from separate_rounds(entry)
        else:
            yield {"type": "error", "message": "That took too many steps. Try splitting the question."}
    except errors.ClientError as exc:
        logger.error("assistant_gemini_client_error", extra={"status": exc.code, "error": str(exc)[:300]})
        if exc.code == 429:
            message = "The assistant has hit its free usage limit for now. Please try again in a minute."
        elif exc.code in (401, 403):
            message = "The assistant is not configured correctly (API key rejected)."
        elif exc.code == 404:
            message = "The configured Gemini model is not available. Check PACKWISE_GEMINI_MODEL."
        else:
            message = "The AI service rejected the request. Please try again."
        yield {"type": "error", "message": message}
    except errors.ServerError as exc:
        logger.error("assistant_gemini_server_error", extra={"status": exc.code})
        yield {"type": "error", "message": "The AI service is having trouble. Please try again."}
    except httpx.HTTPError:
        yield {"type": "error", "message": "Could not reach the AI service. Please try again."}
    finally:
        # Never leave a model turn with unanswered function calls at the end of the history.
        if (
            stored
            and stored[-1].get("role") == "model"
            and any("function_call" in p for p in stored[-1].get("parts", []))
        ):
            stored.pop()
        persist(conversation, stored)


def _log_usage(conversation: Conversation, model: str, finish: str | None, usage: Any) -> None:
    logger.info(
        "assistant_model_call",
        extra={
            "conversation": str(conversation.pk),
            "provider": "gemini",
            "model": model,
            "finish_reason": finish,
            "prompt_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "thinking_tokens": getattr(usage, "thoughts_token_count", None),
        },
    )
