"""Model catalog, per-request model selection and local usage accounting.

The catalog is operator-controlled: hosted entries come from ``MODEL_NAME`` and
``MODEL_BASE_URL``, the local entry comes from the loopback local-model settings,
and extra entries come from the ``MODEL_CATALOG`` JSON environment variable. A
request may only name an id from this catalog, so a client can never supply its
own base URL.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .engine import db
from .studio import authorize

router = APIRouter(prefix="/api/models", tags=["models"])

LOCAL_PREFIX = "local:"
MAX_ENTRIES = 20
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
CATALOG_ENV = "MODEL_CATALOG"
DEFAULT_CONTEXT_CHARS = 12_000


def _hosted_entry():
    key = os.getenv("MODEL_API_KEY", "").strip()
    name = os.getenv("MODEL_NAME", "gpt-4.1-mini").strip()
    if not key or not name:
        return None
    return {
        "id": name,
        "label": name,
        "provider": "hosted",
        "model": name,
        "base_url": os.getenv("MODEL_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "context_chars": int(os.getenv("MODEL_CONTEXT_CHAR_BUDGET", "24000") or 24000),
        "input_cost_per_1k": 0.0,
        "output_cost_per_1k": 0.0,
    }


def _local_entry():
    name = os.getenv("LOCAL_MODEL_NAME", "qwen2.5-coder:7b").strip() or "qwen2.5-coder:7b"
    return {
        "id": LOCAL_PREFIX + name,
        "label": name + " (local)",
        "provider": "local",
        "model": name,
        "base_url": os.getenv("LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/"),
        "context_chars": int(os.getenv("LOCAL_CONTEXT_CHAR_BUDGET", str(DEFAULT_CONTEXT_CHARS)) or DEFAULT_CONTEXT_CHARS),
        "input_cost_per_1k": 0.0,
        "output_cost_per_1k": 0.0,
    }


def _validate_url(value, provider):
    parsed = urlsplit(str(value))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("catalog base_url must be an http(s) endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("catalog base_url cannot contain credentials, query or fragment")
    if provider == "local" and parsed.scheme != "http":
        raise ValueError("local endpoints must use loopback http")
    if provider == "local" and parsed.hostname not in LOOPBACK:
        raise ValueError("local endpoints must be loopback")
    return str(value).rstrip("/")


def _env_entries() -> list[dict]:
    raw = os.getenv(CATALOG_ENV, "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    entries = []
    for item in parsed[:MAX_ENTRIES]:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id") or "").strip()
        model = str(item.get("model") or "").strip()
        base = str(item.get("base_url") or "").strip()
        if not identifier or not model or not base or len(identifier) > 120:
            continue
        provider = "local" if str(item.get("provider")) == "local" else "hosted"
        try:
            base = _validate_url(base, provider)
        except ValueError:
            continue
        try:
            context = int(item.get("context_chars", DEFAULT_CONTEXT_CHARS))
        except (TypeError, ValueError):
            context = DEFAULT_CONTEXT_CHARS
        entries.append({
            "id": identifier,
            "label": str(item.get("label") or identifier)[:120],
            "provider": provider,
            "model": model,
            "base_url": base,
            "context_chars": max(2000, min(context, 400_000)),
            "input_cost_per_1k": float(item.get("input_cost_per_1k") or 0.0),
            "output_cost_per_1k": float(item.get("output_cost_per_1k") or 0.0),
            "api_key_env": str(item.get("api_key_env") or "")[:64],
        })
    return entries


def catalog() -> list[dict]:
    entries: list[dict] = []
    hosted = _hosted_entry()
    if hosted:
        entries.append(hosted)
    entries.append(_local_entry())
    for entry in _env_entries():
        if all(existing["id"] != entry["id"] for existing in entries):
            entries.append(entry)
    return entries


def default_id() -> str:
    if os.getenv("LOCAL_MODEL_ONLY") == "1":
        return _local_entry()["id"]
    hosted = _hosted_entry()
    return hosted["id"] if hosted else ""


def public_catalog() -> list[dict]:
    return [{key: value for key, value in entry.items() if key != "api_key_env"}
            for entry in catalog()]


def resolve(requested=None) -> dict:
    """Return a fully resolved model, or raise ValueError for an unknown id."""
    if requested is not None and not isinstance(requested, str):
        raise ValueError("model must be a string")
    requested = (requested or "").strip()
    if len(requested) > 120:
        raise ValueError("model id is too long")
    entries = catalog()
    chosen = requested or default_id()
    if not chosen:
        raise ValueError(
            "No model is configured: set MODEL_API_KEY, or set LOCAL_MODEL_ONLY=1 "
            "and LOCAL_MODEL_BASE_URL for local inference."
        )
    entry = next((item for item in entries if item["id"] == chosen), None)
    if entry is None:
        raise ValueError("Unknown model: " + chosen)
    resolved = dict(entry)
    if resolved["provider"] == "local":
        resolved["api_key"] = "local"
        resolved["trust_env"] = False
    else:
        key_name = resolved.get("api_key_env") or "MODEL_API_KEY"
        key = os.getenv(key_name, "").strip()
        if not key:
            raise ValueError("Model is not configured: set " + key_name)
        resolved["api_key"] = key
        resolved["trust_env"] = os.getenv("MODEL_TRUST_ENV", "1") == "1"
    resolved["base_url"] = _validate_url(resolved["base_url"], resolved["provider"])
    resolved["context_chars"] = max(2000, min(int(resolved["context_chars"]), 400_000))
    return resolved


def initialize(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS model_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_model_usage_project
        ON model_usage(project, created_at DESC)
    """)


def estimate_tokens(text) -> int:
    return max(0, int(len(str(text or "")) / 4))


def record_usage(project: str, model: str, prompt_chars, completion_chars) -> None:
    """Estimate and store local token usage; no network call is involved."""
    try:
        with db() as conn:
            initialize(conn)
            conn.execute(
                "INSERT INTO model_usage(project,model,prompt_tokens,completion_tokens)"
                " VALUES(?,?,?,?)",
                (project, str(model)[:120], estimate_tokens("x" * int(prompt_chars)),
                 estimate_tokens("x" * int(completion_chars))),
            )
    except Exception:
        # Usage accounting must never break a chat response.
        return


def usage_summary(project: str, limit: int = 8) -> dict:
    with db() as conn:
        initialize(conn)
        rows = conn.execute(
            "SELECT model, SUM(prompt_tokens), SUM(completion_tokens), COUNT(*)"
            " FROM model_usage WHERE project=? GROUP BY model ORDER BY 2 DESC LIMIT ?",
            (project, max(1, min(int(limit), 50))),
        ).fetchall()
    models = [{"model": model, "prompt_tokens": int(prompt or 0),
               "completion_tokens": int(completion or 0), "calls": int(calls or 0)}
              for model, prompt, completion, calls in rows]
    return {
        "project": project,
        "models": models,
        "prompt_tokens": sum(item["prompt_tokens"] for item in models),
        "completion_tokens": sum(item["completion_tokens"] for item in models),
        "calls": sum(item["calls"] for item in models),
        "estimated": True,
    }


class UsageRequest(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


@router.get("")
def list_models(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return {
        "models": public_catalog(),
        "default": default_id(),
        "local_only": os.getenv("LOCAL_MODEL_ONLY") == "1",
    }


@router.get("/{project}/usage")
def usage(project: str, authorization: str | None = Header(default=None)):
    authorize(authorization)
    if not project or len(project) > 64:
        raise HTTPException(400, "Invalid project")
    return usage_summary(project)
