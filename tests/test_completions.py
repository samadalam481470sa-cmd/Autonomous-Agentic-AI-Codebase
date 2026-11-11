"""Inline completion post-processing is deterministic and bounded."""
from services.api import completions


def test_strips_markdown_fences():
    assert completions.clean("```python\nprint(1)\n```") == "print(1)"
    assert completions.clean("```\nvalue = 2\n```") == "value = 2"


def test_drops_an_echoed_prefix():
    prefix = "def add(a, b):\n    return a + b\n"
    cleaned = completions.clean(prefix + "\n\ndef sub(a, b):", prefix)
    assert cleaned == "def sub(a, b):"


def test_caps_the_number_of_lines():
    value = "\n".join(f"line{index}" for index in range(40))
    cleaned = completions.clean(value)
    assert len(cleaned.splitlines()) == completions.MAX_COMPLETION_LINES


def test_empty_and_duplicate_of_suffix_are_dropped():
    assert completions.clean("") == ""
    assert completions.clean("   \n\n") == ""
    assert completions.clean("return 1", "", "return 1") == ""


def test_oversized_completion_is_truncated():
    cleaned = completions.clean("a" * 10_000)
    assert len(cleaned) == completions.MAX_COMPLETION_CHARS


def test_missing_model_is_a_client_error(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from services.api import engine

    monkeypatch.setattr(engine, "DB", ":memory:")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_MODEL_ONLY", raising=False)
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "test-token-1234567890")
    body = completions.CompleteRequest(project="demo", path="a.py", prefix="def f():\n")
    with pytest.raises(HTTPException) as error:
        import asyncio
        asyncio.run(completions.complete(body, authorization="Bearer test-token-1234567890"))
    assert error.value.status_code == 400
