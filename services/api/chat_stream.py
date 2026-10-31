"""Authenticated, opt-in, local-only text streaming for the browser chat.

This intentionally does not stream tool calls or grant file/command permissions.
The existing /api/chat agent path continues to handle tool-enabled requests.
"""
import json
import os
import uuid

import httpx
from .engine import bounded_local_history, db, history
from .local_model import model_settings

MAX_ANSWER_CHARS = 200_000
SYSTEM_PROMPT = (
    "You are a helpful local AI coding assistant. Give accurate code and "
    "explanations. Do not claim to have edited files or executed commands."
)


def encode_event(kind: str, value: dict) -> str:
    """SSE output is JSON-encoded to prevent model text from injecting events."""
    return f"event: {kind}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n"


def save_chat_pair(project: str, message: str, answer: str) -> None:
    """Persist both turns atomically, not a half-finished streamed response."""
    with db() as connection:
        connection.executemany(
            "INSERT INTO messages(id,project,role,content) VALUES(?,?,?,?)",
            [
                (str(uuid.uuid4()), project, "user", message),
                (str(uuid.uuid4()), project, "assistant", answer),
            ],
        )


def default_client():
    # trust_env=False prevents HTTPS_PROXY and related env values rerouting
    # the local-only model request to an external service.
    return httpx.AsyncClient(timeout=180, trust_env=False, follow_redirects=False)


def output_token_limit() -> int:
    try:
        value = int(os.getenv("LOCAL_MAX_OUTPUT_TOKENS", "1024"))
    except (ValueError, TypeError):
        value = 1024
    return max(64, min(value, 8192))


async def stream_local_chat(project: str, message: str, client_factory=None):
    """Emit SSE events while forwarding local token deltas.

    A final [DONE] and nonempty text are required before persisting the pair.
    Interrupted streams (including client disconnects) are not persisted.
    """
    settings = model_settings()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history(project))
    messages.append({"role": "user", "content": message})
    messages = bounded_local_history(
        messages, os.getenv("LOCAL_CONTEXT_CHAR_BUDGET", "12000")
    )
    payload = {
        "model": settings["model"],
        "messages": messages,
        "stream": True,
        "max_tokens": output_token_limit(),
        "tool_choice": "none",
    }

    fragments = []
    length = 0
    finished = False
    truncated = False
    factory = client_factory or default_client
    try:
        async with factory() as client:
            async with client.stream(
                "POST",
                settings["base_url"] + "/chat/completions",
                headers={"Authorization": "Bearer local"},
                json=payload,
            ) as response:
                response.raise_for_status()
                if not response.headers.get("content-type", "").lower().startswith(
                    "text/event-stream"
                ):
                    raise ValueError("Upstream did not provide SSE")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        finished = True
                        break
                    if not data:
                        continue
                    event = json.loads(data)
                    choices = event.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        raise ValueError("Invalid SSE choice")
                    if choice.get("finish_reason") == "length":
                        truncated = True
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        raise ValueError("Invalid SSE delta")
                    part = delta.get("content")
                    if part is None:
                        continue
                    if not isinstance(part, str):
                        raise ValueError("Invalid SSE text content")
                    if part:
                        length += len(part)
                        if length > MAX_ANSWER_CHARS:
                            raise ValueError("Stream exceeded answer size limit")
                        fragments.append(part)
                        yield encode_event("delta", {"text": part})
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
        yield encode_event("error", {
            "message": "Local model streaming failed; the incomplete answer was not saved."
        })
        return

    answer = "".join(fragments)
    if not finished or not answer.strip():
        yield encode_event("error", {
            "message": "Local model ended without a complete text response; nothing was saved."
        })
        return

    save_chat_pair(project, message, answer)
    yield encode_event("done", {"saved": True, "truncated": truncated})
