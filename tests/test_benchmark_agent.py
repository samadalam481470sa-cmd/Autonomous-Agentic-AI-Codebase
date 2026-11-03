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


def test_model_call_writes_only_validated_files(tmp_path):
    def handler(request):
        body = json.loads(request.content)
        assert body["temperature"] == 0
        assert "BENCHMARK_PROMPT" not in request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "files": {"solution.py": "def add(a, b):\n    return a + b\n"}
        })}}]})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    plan = benchmark_agent.solve(
        "Implement add(a, b).", tmp_path, client=client,
        env={"MODEL_API_KEY": "test", "MODEL_NAME": "test-model"},
    )
    assert plan == {"solution.py": "def add(a, b):\n    return a + b\n"}
    assert (tmp_path / "solution.py").read_text() == "def add(a, b):\n    return a + b\n"
