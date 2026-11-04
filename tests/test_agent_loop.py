"""The lead executor may run the project's own check command in its worktree."""
import asyncio
import json
import os
import subprocess

from services.api import engine, events, executor


def make_repo(tmp_path, monkeypatch):
    root = tmp_path / "workspaces" / "demo"
    root.mkdir(parents=True)
    env = {
        **os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.test",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.test",
    }
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True, env=env)
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "events.sqlite3"))
    monkeypatch.setenv("POLICY_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("WORKTREES_ROOT", str(tmp_path / "worktrees"))
    return root


def fake_model(actions):
    calls = []

    async def complete(system, user, max_tokens=1200):
        calls.append(user)
        return json.dumps(actions[min(len(calls) - 1, len(actions) - 1)])
    return complete


def test_run_tests_executes_the_toolchain_inside_the_worktree(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    complete = fake_model([
        {"tool": "run_tests",
         "arguments": {"language": "python", "action": "check", "target": "app.py"}},
        {"final": "Checked the file."},
    ])
    result = asyncio.run(executor.execute(
        "demo", "Check that the project compiles", role="tester",
        autonomy="sandbox", complete=complete,
    ))
    assert result["status"] == "completed"
    completed = [item for item in events.list_events(result["run_id"])
                 if item["type"] == "tool.completed"]
    payload = json.loads(completed[0]["payload"]["result"])
    assert payload["action"] == "check"
    assert payload["passed"] is True
    assert "py_compile" in " ".join(payload["steps"][0]["argv"])
    # The run was allowed by policy, not denied and retried.
    assert not [item for item in events.list_events(result["run_id"])
                if item["type"] == "tool.denied"]


def test_run_tests_needs_a_language_or_a_target(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    complete = fake_model([
        {"tool": "run_tests", "arguments": {}},
        {"final": "Stopped."},
    ])
    result = asyncio.run(executor.execute(
        "demo", "Run the tests without naming a language", role="tester",
        autonomy="sandbox", complete=complete,
    ))
    completed = [item for item in events.list_events(result["run_id"])
                 if item["type"] == "tool.completed"]
    assert "needs a language or a target file" in completed[0]["payload"]["result"]


def test_worktree_autonomy_still_requires_approval_for_tests(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    complete = fake_model([
        {"tool": "run_tests", "arguments": {"language": "python", "target": "app.py"}},
        {"final": "Not run."},
    ])
    result = asyncio.run(executor.execute(
        "demo", "Run the tests with default autonomy", role="tester",
        complete=complete,
    ))
    denied = [item for item in events.list_events(result["run_id"])
              if item["type"] == "tool.denied"]
    assert denied[0]["payload"]["reason"] == "command_requires_approval"
