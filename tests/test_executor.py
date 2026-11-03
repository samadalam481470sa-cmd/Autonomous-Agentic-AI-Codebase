import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from services.api import engine, events, executor, policy


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
        index = min(len(calls) - 1, len(actions) - 1)
        return json.dumps(actions[index])
    return complete, calls


def test_executor_writes_only_the_worktree_and_logs_every_step(tmp_path, monkeypatch):
    root = make_repo(tmp_path, monkeypatch)
    complete, calls = fake_model([
        {"tool": "read_file", "arguments": {"path": "app.py"}},
        {"tool": "write_file", "arguments": {"path": "app.py", "content": "value = 2\n"}},
        {"final": "Updated app.py in the worktree."},
    ])
    result = asyncio.run(executor.execute("demo", "Change app.py to value 2", complete=complete))
    assert result["status"] == "completed"
    assert result["final"].startswith("Updated app.py")
    assert result["turns"] == 3
    assert result["changes"]["files"] == ["app.py"]
    worktree = (root.parent.parent / "worktrees").glob("*/app.py")
    assert next(worktree).read_text(encoding="utf-8") == "value = 2\n"
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    assert calls[0].startswith("Goal: Change app.py")
    types = [item["type"] for item in events.list_events(result["run_id"])]
    assert types[:2] == ["executor.started", "tool.called"]
    assert types.count("tool.completed") == 2
    assert types[-1] == "executor.completed"
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(audit) == 2
    assert json.loads(audit[1])["decision"] == "allow"


def test_ask_mode_denies_writes_and_keeps_the_worktree_clean(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    complete, _ = fake_model([
        {"tool": "write_file", "arguments": {"path": "app.py", "content": "bad\n"}},
        {"final": "I cannot write in ask mode."},
    ])
    result = asyncio.run(executor.execute(
        "demo", "Change app.py to bad", autonomy="ask", complete=complete
    ))
    assert result["status"] == "completed"
    assert result["changes"]["clean"] is True
    types = [item["type"] for item in events.list_events(result["run_id"])]
    assert "tool.denied" in types
    denied = next(item for item in events.list_events(result["run_id"])
                  if item["type"] == "tool.denied")
    assert denied["payload"]["reason"] == "ask_mode_cannot_change_state"


def test_commands_are_unavailable_even_with_approval(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    complete, _ = fake_model([
        {"tool": "run_command", "arguments": {"command": "rm -rf ."}},
        {"final": "No command was run."},
    ])
    result = asyncio.run(executor.execute(
        "demo", "Delete everything with a command", approved={"run_command"},
        complete=complete,
    ))
    completed = [item for item in events.list_events(result["run_id"])
                 if item["type"] == "tool.completed"]
    assert "never runs host commands" in completed[0]["payload"]["result"]
    assert (Path(result["worktree"]["path"]) / "app.py").exists()


def test_path_escape_and_unknown_role_are_rejected(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    complete, _ = fake_model([
        {"tool": "write_file", "arguments": {"path": "../escape.py", "content": "x"}},
        {"final": "Stopped."},
    ])
    result = asyncio.run(executor.execute(
        "demo", "Attempt an escape write", complete=complete
    ))
    assert not (Path(result["worktree"]["path"]).parent / "escape.py").exists()
    denied = [item for item in events.list_events(result["run_id"])
              if item["type"] == "tool.denied"]
    assert denied[0]["payload"]["reason"] == "invalid_target"
    with pytest.raises(ValueError):
        asyncio.run(executor.execute("demo", "A valid goal here", role="planner"))
    with pytest.raises(ValueError):
        asyncio.run(executor.execute("demo", "A valid goal here", autonomy="root"))


def test_non_json_prose_is_a_final_answer(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)

    async def prose(system, user, max_tokens=1200):
        return "No safe change is needed."

    result = asyncio.run(executor.execute(
        "demo", "Review this repository", complete=prose
    ))
    assert result["status"] == "completed"
    assert result["final"] == "No safe change is needed."
    assert result["changes"]["clean"] is True
