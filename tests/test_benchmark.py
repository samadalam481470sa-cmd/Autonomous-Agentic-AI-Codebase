import json
import os
import stat
import sys

import pytest

import scripts.run_benchmark as benchmark


def test_benchmark_has_thirty_unique_executable_tasks():
    tasks = benchmark.load_tasks()
    assert len(tasks) == 30
    assert len({task["id"] for task in tasks}) == 30
    assert {task["language"] for task in tasks} == {"python", "javascript"}
    for task in tasks:
        assert task["files"]
        assert task["test"][0] in {"{python}", "node"}


def test_starter_fails_and_reference_solution_passes():
    task = {
        "id": "py-sample", "language": "python",
        "prompt": "Implement add(a, b).",
        "files": {"solution.py": "def add(a, b):\n    raise NotImplementedError\n"},
        "test": ["{python}", "-c", "from solution import add; assert add(2, 3) == 5"],
        "timeout": 5,
    }
    failed = benchmark.run_task(task)
    assert failed["passed"] is False
    passed = benchmark.run_task(task, solution_files={"solution.py": "def add(a, b):\n    return a + b\n"})
    assert passed["passed"] is True


def test_agent_command_receives_prompt_and_can_solve(tmp_path):
    script = tmp_path / "solve.py"
    script.write_text(
        "import os, pathlib\n"
        "assert os.environ['BENCHMARK_TASK_ID'] == 'py-sample'\n"
        "assert 'add' in os.environ['BENCHMARK_PROMPT']\n"
        "pathlib.Path('solution.py').write_text('def add(a, b):\\n    return a + b\\n')\n",
        encoding="utf-8",
    )
    task = {
        "id": "py-sample", "language": "python", "prompt": "Implement add(a, b).",
        "files": {"solution.py": "def add(a, b):\n    raise NotImplementedError\n"},
        "test": ["{python}", "-c", "from solution import add; assert add(2, 3) == 5"],
        "timeout": 5,
    }
    result = benchmark.run_task(task, agent_command=f"{sys.executable} {script}")
    assert result["agent"]["ran"] is True
    assert result["passed"] is True


def test_unsafe_task_paths_and_wrong_task_count_are_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    task = {
        "id": "py-sample", "language": "python", "prompt": "Implement add(a, b).",
        "files": {"../escape.py": "x"}, "test": ["{python}", "-c", "pass"],
    }
    bad.write_text(json.dumps([task] * 30), encoding="utf-8")
    with pytest.raises(ValueError):
        benchmark.load_tasks(bad)
