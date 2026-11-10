"""Local model failures should explain what to fix, not hide the cause."""
import asyncio
import json

import httpx
import pytest

from services.api import context_refs, engine, models, rules


def response(status, payload=None, text=None):
    if text is None:
        text = json.dumps(payload or {})
    return httpx.Response(
        status,
        request=httpx.Request("POST", "http://127.0.0.1:11434/v1/chat/completions"),
        text=text,
    )


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append(dict(json) if json is not None else json)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def prepare(monkeypatch, responses):
    chosen = {
        "id": "local:qwen2.5-coder:7b",
        "provider": "local",
        "api_key": "local",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5-coder:7b",
        "context_chars": 12000,
    }
    monkeypatch.setenv("SEMANTIC_RAG", "0")
    monkeypatch.setattr(engine, "save", lambda *args: None)
    monkeypatch.setattr(engine, "history", lambda project: [])
    monkeypatch.setattr(engine, "capture_learning", lambda *args, **kwargs: None)
    monkeypatch.setattr(context_refs, "prompt_block", lambda *args, **kwargs: "")
    monkeypatch.setattr(rules, "prompt_block", lambda *args, **kwargs: "")
    monkeypatch.setattr(models, "resolve", lambda requested=None: chosen)
    monkeypatch.setattr(models, "record_usage", lambda *args: None)
    client = FakeClient(responses)
    monkeypatch.setattr(engine.httpx, "AsyncClient", lambda **kwargs: client)
    return client


def test_tool_rejection_retries_without_tools(monkeypatch):
    client = prepare(monkeypatch, [
        response(400, text='{"error":"model does not support tools"}'),
        response(200, {"choices": [{"message": {"content": "Plain answer"}}]}),
    ])

    answer = asyncio.run(engine.respond("demo", "explain this project"))

    assert answer == "Plain answer"
    assert "tools" in client.calls[0]
    assert "tools" not in client.calls[1]
    assert "tool_choice" not in client.calls[1]


def test_missing_local_model_names_the_pull_command(monkeypatch):
    prepare(monkeypatch, [response(404, text='{"error":"model not found"}')])

    with pytest.raises(engine.ModelCallError) as caught:
        asyncio.run(engine.respond("demo", "hello"))

    assert caught.value.status_code == 503
    assert "ollama pull qwen2.5-coder:7b" in str(caught.value)


def test_unreachable_local_model_names_ollama(monkeypatch):
    prepare(monkeypatch, [httpx.ConnectError("connection refused")])

    with pytest.raises(engine.ModelCallError) as caught:
        asyncio.run(engine.respond("demo", "hello"))

    assert caught.value.status_code == 503
    assert "ollama serve" in str(caught.value)
    assert "127.0.0.1:11434" in str(caught.value)


def test_empty_model_answer_is_an_error_not_a_bubble(monkeypatch):
    prepare(monkeypatch, [
        response(200, {"choices": [{"message": {"content": ""}}]}),
    ])

    with pytest.raises(engine.ModelCallError) as caught:
        asyncio.run(engine.respond("demo", "hello"))

    assert caught.value.status_code == 502
    assert "empty response" in str(caught.value)
