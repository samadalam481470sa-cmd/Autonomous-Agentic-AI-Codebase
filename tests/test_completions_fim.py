"""Native FIM payloads stay small, bounded and compatible with llama.cpp/vLLM."""
import asyncio
import json

import httpx

from services.api import completions
from services.api.completions import clean, fim_payload


def _local_model(monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("LOCAL_MODEL_ONLY", "1")
    monkeypatch.setenv("LOCAL_MODEL_BASE_URL", "http://127.0.0.1:8088/v1")
    monkeypatch.setenv("LOCAL_MODEL_NAME", "coder")


def _stub(monkeypatch, handler):
    """Send the endpoint's model traffic to a mock transport instead of a server."""
    real = httpx.AsyncClient
    calls = []

    def record(request):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(record), trust_env=False),
    )
    return calls


def test_fim_payload_carries_prefix_and_suffix():
    body = fim_payload("local-model", "def add(a, b):\n", "    return a + b\n", 64)
    assert body["model"] == "local-model"
    assert body["prompt"] == "def add(a, b):\n"
    assert body["suffix"] == "    return a + b\n"
    assert body["max_tokens"] == 64
    assert body["temperature"] < 0.3
    assert body["stop"]


def test_fim_output_is_cleaned_like_chat_output():
    assert clean("```python\n    return a + b\n```") == "    return a + b"


def test_fim_mode_posts_prefix_and_suffix_to_completions(monkeypatch):
    _local_model(monkeypatch)
    monkeypatch.setenv("COMPLETION_FIM", "1")
    calls = _stub(
        monkeypatch,
        lambda request: httpx.Response(200, json={"choices": [{"text": "```python\n    return a + b\n```"}]}),
    )
    body = completions.CompleteRequest(
        project="demo",
        path="a.py",
        prefix="def add(a, b):\n",
        suffix="\nprint(add(1, 2))\n",
    )
    result = asyncio.run(completions.complete(body, authorization="Bearer test-token"))

    assert str(calls[0].url) == "http://127.0.0.1:8088/v1/completions"
    sent = json.loads(calls[0].content)
    assert sent["prompt"] == "def add(a, b):\n"
    assert sent["suffix"] == "\nprint(add(1, 2))\n"
    assert sent["max_tokens"] == 128
    assert sent["stop"]
    assert result["completion"] == "    return a + b"
    assert result["provider"] == "local"


def test_chat_route_is_used_when_fim_is_off(monkeypatch):
    _local_model(monkeypatch)
    monkeypatch.delenv("COMPLETION_FIM", raising=False)
    calls = _stub(
        monkeypatch,
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "    return a - b"}}]}),
    )
    body = completions.CompleteRequest(project="demo", path="a.py", prefix="def add(a, b):\n")
    result = asyncio.run(completions.complete(body, authorization="Bearer test-token"))

    assert str(calls[0].url) == "http://127.0.0.1:8088/v1/chat/completions"
    assert "suffix" not in json.loads(calls[0].content)
    assert result["completion"] == "    return a - b"


def test_non_text_completion_is_refused(monkeypatch):
    from fastapi import HTTPException
    import pytest

    _local_model(monkeypatch)
    monkeypatch.setenv("COMPLETION_FIM", "1")
    _stub(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"text": None}]}))
    body = completions.CompleteRequest(project="demo", path="a.py", prefix="def add(a, b):\n")
    with pytest.raises(HTTPException) as error:
        asyncio.run(completions.complete(body, authorization="Bearer test-token"))
    assert error.value.status_code == 502
