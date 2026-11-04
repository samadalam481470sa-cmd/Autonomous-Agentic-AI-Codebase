"""Native FIM payloads stay small, bounded and compatible with llama.cpp/vLLM."""
from services.api.completions import clean, fim_payload


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
