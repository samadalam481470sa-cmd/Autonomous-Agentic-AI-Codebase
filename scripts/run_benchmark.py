#!/usr/bin/env python3
"""Run the 30-task local coding benchmark in disposable directories.

Each starter is expected to fail. An optional ``--agent-command`` is invoked in
the task copy with BENCHMARK_TASK_ID and BENCHMARK_PROMPT set; it must edit files
in its current directory. Tests run with no shell, a timeout, and the task's
declared files only. The starter baseline is a real measurement, not a score
for a model: it proves the tasks start red.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = ROOT / "evals" / "benchmark" / "tasks.json"
EXPECTED_TASKS = 30
MAX_FILE_BYTES = 200_000


def load_tasks(path=DEFAULT_TASKS) -> list[dict]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) != EXPECTED_TASKS:
        raise ValueError(f"Benchmark requires exactly {EXPECTED_TASKS} tasks")
    seen = set()
    for task in data:
        if not isinstance(task, dict):
            raise ValueError("Each task must be an object")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-z0-9-]{3,64}", task_id):
            raise ValueError("Invalid task id")
        if task_id in seen:
            raise ValueError(f"Duplicate task id: {task_id}")
        seen.add(task_id)
        if not isinstance(task.get("prompt"), str) or len(task["prompt"]) < 10:
            raise ValueError(f"{task_id}: prompt is too short")
        files = task.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"{task_id}: files are required")
        for name, content in files.items():
            if not isinstance(name, str) or not isinstance(content, str):
                raise ValueError(f"{task_id}: invalid file entry")
            target = Path(name)
            if target.is_absolute() or ".." in target.parts or not name.strip():
                raise ValueError(f"{task_id}: file path escapes the task directory")
            if len(content.encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError(f"{task_id}: file is too large")
        command = task.get("test")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
            raise ValueError(f"{task_id}: test must be an argv list")
        timeout = task.get("timeout", 10)
        if not isinstance(timeout, int) or not 1 <= timeout <= 120:
            raise ValueError(f"{task_id}: invalid timeout")
    return data


def _write_files(workspace: Path, files: dict) -> None:
    for name, content in files.items():
        destination = (workspace / name).resolve()
        if not destination.is_relative_to(workspace):
            raise ValueError("Refusing to write outside the task directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def run_task(task: dict, *, solution_files: dict | None = None,
             agent_command: str | None = None, agent_timeout: int = 120) -> dict:
    with tempfile.TemporaryDirectory(prefix="bench-") as tmp:
        workspace = Path(tmp).resolve()
        _write_files(workspace, task["files"])
        if solution_files:
            _write_files(workspace, solution_files)
        agent = {"ran": False, "exit_code": None, "error": ""}
        if agent_command:
            argv = shlex.split(agent_command)
            if not argv:
                raise ValueError("agent command is empty")
            environment = {
                **os.environ,
                "BENCHMARK_TASK_ID": task["id"],
                "BENCHMARK_PROMPT": task["prompt"],
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            try:
                completed = subprocess.run(
                    argv, cwd=workspace, capture_output=True, text=True,
                    timeout=agent_timeout, env=environment, check=False,
                )
                agent = {"ran": True, "exit_code": completed.returncode,
                         "error": (completed.stderr or "")[-800:]}
            except subprocess.TimeoutExpired:
                agent = {"ran": True, "exit_code": None, "error": "agent timed out"}
            except OSError as error:
                agent = {"ran": False, "exit_code": None, "error": str(error)[:800]}
        command = [
            sys.executable if part == "{python}" else part
            for part in task["test"]
        ]
        started = time.monotonic()
        try:
            result = subprocess.run(
                command, cwd=workspace, capture_output=True, text=True,
                timeout=task.get("timeout", 10), check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            passed = result.returncode == 0
            output = (result.stderr or result.stdout or "")[-1200:]
        except subprocess.TimeoutExpired:
            passed = False
            output = "test timed out"
        return {
            "id": task["id"], "language": task.get("language", "unknown"),
            "passed": passed, "agent": agent,
            "seconds": round(time.monotonic() - started, 3), "output": output,
        }


def run_benchmark(tasks: list[dict], *, agent_command=None, agent_timeout=120) -> dict:
    results = [
        run_task(task, agent_command=agent_command, agent_timeout=agent_timeout)
        for task in tasks
    ]
    passed = sum(1 for item in results if item["passed"])
    agent_failures = sum(
        1 for item in results
        if agent_command and (not item["agent"]["ran"] or item["agent"]["exit_code"] != 0)
    )
    return {
        "kind": "agent" if agent_command else "starter-baseline",
        "agent_command": agent_command,
        "total": len(results), "passed": passed,
        "failed": len(results) - passed,
        "agent_failures": agent_failures,
        "results": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--agent-command", default=None,
                        help="Executable run inside each task copy; prompt is in BENCHMARK_PROMPT.")
    parser.add_argument("--agent-timeout", type=int, default=120)
    parser.add_argument("--json", default=None, help="Write the full result object here.")
    parser.add_argument("--markdown", default=None, help="Write a compact report here.")
    parser.add_argument("--require-pass", type=int, default=None,
                        help="Exit 1 when fewer tasks pass than this threshold.")
    args = parser.parse_args(argv)
    try:
        tasks = load_tasks(args.tasks)
        summary = run_benchmark(tasks, agent_command=args.agent_command,
                                agent_timeout=args.agent_timeout)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"benchmark error: {error}", file=sys.stderr)
        return 2
    for item in summary["results"]:
        state = "PASS" if item["passed"] else "FAIL"
        print(f"{state}  {item['id']:<26} {item['seconds']:>5.2f}s")
    print(f"\n{summary['passed']}/{summary['total']} passed ({summary['kind']}); "
          f"agent failures: {summary['agent_failures']}")
    if args.agent_command and summary["agent_failures"] == summary["total"]:
        print("agent failed for every task; refusing to record this as a score", file=sys.stderr)
        return 2
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        lines = ["# Coding benchmark", "", f"- Kind: {summary['kind']}",
                 f"- Passed: {summary['passed']}/{summary['total']}", "",
                 "| Task | Language | Result |", "| --- | --- | --- |"]
        lines += [f"| {item['id']} | {item['language']} | {'pass' if item['passed'] else 'fail'} |"
                  for item in summary["results"]]
        Path(args.markdown).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.require_pass is not None and summary["passed"] < args.require_pass:
        print(f"required {args.require_pass} passes, got {summary['passed']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
