import json

import httpx
import pytest

from scripts import benchmark_agent


def test_missing_model_configuration_is_explicit():
    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        benchmark_agent.settings({})
    with pytest.raises(RuntimeError, match="LOCAL_MODEL_NAME"):
        benchmark_agent.settings({"LOCAL_MODEL_ONLY": "1", "LOCAL_MODEL_BASE_URL": "http://127.0.0.1:8088/v1"})


def test_plan_parser_accepts_fences_and_rejects_escapes():
    assert benchmark_agent.parse_plan(
        '```json\n{"files":{"solution.py":"def add(a,b):\\n    return a+b\\n"}}\n```'
    ) == {"solution.py": "def add(a,b):\n    return a+b\n"}
    for bad in (
        '{"files":{"../escape.py":"x"}}',
        '{"files":{"/etc/passwd":"x"}}',
        '{"files":{".git/config":"x"}}',
        '{"files":{}}',
    ):
        with pytest.raises(ValueError):
            benchmark_agent.parse_plan(bad)


def test_single_file_model_returns_raw_code_and_it_is_written(tmp_path):
    responses = iter([
        "def add(a, b):\n    raise NotImplementedError\n",
        "```python\ndef add(a, b):\n    return a + b\n```",
    ])

    def handler(request):
        body = json.loads(request.content)
        assert body["temperature"] == 0
        return httpx.Response(200, json={"choices": [{"message": {"content": next(responses)}}]})

    (tmp_path / "solution.py").write_text("def add(a, b):\n    raise NotImplementedError\n")
    plan = benchmark_agent.solve(
        "Implement add(a, b).", tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)),
        env={"MODEL_API_KEY": "test", "MODEL_NAME": "test-model"},
    )
    assert set(plan) == {"solution.py"}
    assert "return a + b" in (tmp_path / "solution.py").read_text()


def test_model_call_rejects_json_placeholder_for_single_file(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{\"files\":{\"relative/path\":\"x\"}}\n```"}}]})

    (tmp_path / "solution.py").write_text("def add(a, b):\n    raise NotImplementedError\n")
    with pytest.raises(ValueError, match="usable code"):
        benchmark_agent.solve(
            "Implement add(a, b).", tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler)),
            env={"MODEL_API_KEY": "test", "MODEL_NAME": "test-model"},
        )
