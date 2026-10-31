"""The local live-chat path must not silently save incomplete answers."""
import asyncio
import json

import httpx
import pytest
from services.api import chat_stream


def records(events):
    result = []
    for item in events:
        lines = item.strip().splitlines()
        result.append((lines[0][7:], json.loads(lines[1][6:])))
    return result


def make_transport(body, status=200, content_type="text/event-stream", requests=None):
    def handler(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(
            status, headers={"content-type": content_type}, text=body
        )
    transport = httpx.MockTransport(handler)
    return lambda: httpx.AsyncClient(transport=transport, trust_env=False)


def run_stream(monkeypatch, body, status=200, content_type="text/event-stream"):
    saved = []
    requests = []
    monkeypatch.setattr(chat_stream, "history", lambda project: [])
    monkeypatch.setattr(chat_stream, "save_chat_pair", lambda *args: saved.append(args))
    monkeypatch.setattr(chat_stream, "model_settings", lambda: {
        "base_url": "http://127.0.0.1:8088/v1", "model": "local-model"
    })
    factory = make_transport(body, status, content_type, requests)
    async def collect():
        return [item async for item in chat_stream.stream_local_chat("demo", "hi", factory)]
    events = records(asyncio.run(collect()))
    return events, saved, requests


def test_token_deltas_stream_and_pair_is_saved_atomically(monkeypatch):
    upstream = (
        'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    events, saved, requests = run_stream(monkeypatch, upstream)
    assert events == [
        ("delta", {"text": "Hello "}),
        ("delta", {"text": "world"}),
        ("done", {"saved": True, "truncated": False}),
    ]
    assert saved == [("demo", "hi", "Hello world")]
    assert str(requests[0].url) == "http://127.0.0.1:8088/v1/chat/completions"
    body = json.loads(requests[0].content)
    assert body["stream"] is True
    assert body["tool_choice"] == "none"
    assert body["messages"][-1] == {"role": "user", "content": "hi"}


@pytest.mark.parametrize("upstream,status,content_type", [
    ('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', 200, "text/event-stream"),
    ("not sse", 200, "application/json"),
    ("failure", 502, "text/event-stream"),
    ("data: broken json\n\n", 200, "text/event-stream"),
])
def test_incomplete_stream_never_persists(monkeypatch, upstream, status, content_type):
    events, saved, _ = run_stream(monkeypatch, upstream, status, content_type)
    assert events[-1][0] == "error"
    assert not saved


def test_rejects_oversized_stream_without_saving(monkeypatch):
    monkeypatch.setattr(chat_stream, "MAX_ANSWER_CHARS", 4)
    upstream = (
        'data: {"choices":[{"delta":{"content":"too much"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    events, saved, _ = run_stream(monkeypatch, upstream)
    assert events == [("error", {
        "message": "Local model streaming failed; the incomplete answer was not saved."
    })]
    assert not saved


def test_sse_encoder_does_not_allow_new_model_event_lines():
    text = "Hello\n\nevent: done\ndata: dangerous"
    output = chat_stream.encode_event("delta", {"text": text})
    assert [line for line in output.splitlines() if line.startswith("event: ")] == ["event: delta"]
    assert len(records([output])) == 1


def test_output_limit_handles_invalid_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_MAX_OUTPUT_TOKENS", "bad")
    assert chat_stream.output_token_limit() == 1024
    monkeypatch.setenv("LOCAL_MAX_OUTPUT_TOKENS", "999999")
    assert chat_stream.output_token_limit() == 8192
