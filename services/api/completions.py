"""Fill-in-the-middle inline completions for the editor surfaces.

Kept deliberately small and bounded: a short context window, a small output
budget, a hard timeout and deterministic post-processing. The endpoint never
writes files and never accepts a client-supplied base URL.
"""
from __future__ import annotations

import os
import re
import time

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import models
from .studio import authorize

router = APIRouter(prefix="/api/ai", tags=["completions"])

MAX_CONTEXT_CHARS = 20_000
MAX_COMPLETION_CHARS = 2_000
MAX_COMPLETION_LINES = 12
# Keep the indentation of the first content line: only the fence line is removed.
FENCE = re.compile(r"^```[A-Za-z0-9_+#.-]*[ \t]*\r?\n?|\n?```[ \t]*$")
SYSTEM_PROMPT = (
    "You are an inline code completion engine inside an editor. Return ONLY the "
    "exact text that belongs at the cursor. No explanation, no markdown fences, "
    "no repetition of the code before the cursor. Prefer one to eight lines that "
    "continue the existing style. Return an empty string when no completion fits."
)


class CompleteRequest(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    path: str = Field(default="", max_length=512)
    prefix: str = Field(default="", max_length=MAX_CONTEXT_CHARS)
    suffix: str = Field(default="", max_length=MAX_CONTEXT_CHARS)
    max_tokens: int = Field(default=128, ge=16, le=256)
    model: str | None = Field(default=None, max_length=120)


def clean(text, prefix: str = "", suffix: str = "") -> str:
    """Strip fences, echoed context and runaway output from a model completion."""
    value = str(text or "").replace("\r\n", "\n")
    if value.lstrip().startswith("```") or value.rstrip().endswith("```"):
        value = FENCE.sub("", value.strip())
    value = value.replace("```", "")
    value = value.strip("\n")
    if not value.strip():
        return ""
    # Some models echo the tail of the prefix; drop that overlap.
    tail = prefix[-240:]
    for size in range(len(tail), 7, -8):
        if value.startswith(tail[-size:]):
            value = value[size:].lstrip("\n")
            break
    lines = []
    for line in value.split("\n"):
        if len(lines) >= MAX_COMPLETION_LINES:
            break
        lines.append(line)
    value = "\n".join(lines).rstrip()
    if len(value) > MAX_COMPLETION_CHARS:
        value = value[:MAX_COMPLETION_CHARS]
    if suffix and value.strip() and value.strip() == suffix.strip():
        return ""
    return value


def _prompt(path: str, prefix: str, suffix: str) -> str:
    language = path.rsplit(".", 1)[-1].lower() if "." in path else "unknown"
    return (
        f"File: {path or 'untitled'}\nLanguage: {language}\n"
        "<BEFORE_CURSOR>\n" + prefix + "\n<AFTER_CURSOR>\n" + suffix +
        "\n<MISSING_CODE>\n"
    )


def fim_payload(model: str, prefix: str, suffix: str, max_tokens: int) -> dict:
    """Body for a native fill-in-the-middle /completions endpoint (llama.cpp, vLLM)."""
    return {
        "model": model,
        "prompt": prefix,
        "suffix": suffix,
        "max_tokens": max_tokens,
        "temperature": 0.15,
        "stop": ["<|file_separator|>", "\n\n\n\n"],
    }


async def fim_text(*, base_url: str, api_key: str, model: str, prefix: str, suffix: str,
                   max_tokens: int, trust_env: bool, timeout: float) -> dict:
    """One native FIM request; callers fall back to the chat route on failure."""
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout, trust_env=trust_env,
                                 follow_redirects=False) as client:
        response = await client.post(base_url + "/completions",
                                     headers={"Authorization": "Bearer " + api_key},
                                     json=fim_payload(model, prefix, suffix, max_tokens))
        response.raise_for_status()
        data = response.json()
    text = data["choices"][0].get("text")
    if not isinstance(text, str):
        raise ValueError("model returned non-text completion")
    return {"text": text, "elapsed_ms": int((time.monotonic() - started) * 1000)}


async def complete_text(*, base_url: str, api_key: str, model: str, prompt: str,
                        max_tokens: int, trust_env: bool, timeout: float) -> dict:
    started = time.monotonic()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.15,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=timeout, trust_env=trust_env,
                                 follow_redirects=False) as client:
        response = await client.post(base_url + "/chat/completions",
                                     headers={"Authorization": "Bearer " + api_key},
                                     json=payload)
        response.raise_for_status()
        data = response.json()
    text = data["choices"][0]["message"].get("content")
    if not isinstance(text, str):
        raise ValueError("model returned non-text completion")
    return {"text": text, "elapsed_ms": int((time.monotonic() - started) * 1000)}


@router.post("/complete")
async def complete(body: CompleteRequest,
                   authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        model = models.resolve(body.model)
    except ValueError as error:
        raise HTTPException(400, str(error))
    prompt = _prompt(body.path, body.prefix[-MAX_CONTEXT_CHARS:],
                     body.suffix[:MAX_CONTEXT_CHARS])
    max_tokens = min(body.max_tokens,
                     int(os.getenv("COMPLETION_MAX_TOKENS", "160") or 160))
    timeout = float(os.getenv("COMPLETION_TIMEOUT_SECONDS", "12") or 12)
    try:
        if os.getenv("COMPLETION_FIM") == "1":
            result = await fim_text(
                base_url=model["base_url"], api_key=model["api_key"],
                model=model["model"], prefix=body.prefix[-MAX_CONTEXT_CHARS:],
                suffix=body.suffix[:MAX_CONTEXT_CHARS], max_tokens=max_tokens,
                trust_env=bool(model["trust_env"]), timeout=timeout,
            )
        else:
            result = await complete_text(
                base_url=model["base_url"], api_key=model["api_key"],
                model=model["model"], prompt=prompt, max_tokens=max_tokens,
                trust_env=bool(model["trust_env"]), timeout=timeout,
            )
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        raise HTTPException(502, "Completion model did not return usable text")
    completion = clean(result["text"], body.prefix, body.suffix)
    return {
        "completion": completion,
        "model": model["id"],
        "provider": model["provider"],
        "elapsed_ms": result["elapsed_ms"],
    }
