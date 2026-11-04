"""Commands are argv-only, allowlisted, digest-approved and auditable."""
import shutil

import pytest
from fastapi import HTTPException

from services.api import commands, engine

PYTHON = next((name for name in ("python3", "python") if shutil.which(name)), None)


def test_validate_normalizes_and_enforces_the_allowlist():
    assert commands.validate(["python", "-m", "pytest", "-q"])[0] == "python"
    with pytest.raises(ValueError):
        commands.validate(["rm", "-rf", "/"])
    with pytest.raises(ValueError):
        commands.validate(["sh", "-c", "ls"])
    with pytest.raises(ValueError):
        commands.validate(["curl", "http://example.test"])


def test_shell_metacharacters_and_dangerous_git_are_refused():
    for argv in (
        ["python", "-c", "a; b"],
        ["python", "-c", "a | b"],
        ["git", "push"],
        ["git", "reset", "--hard"],
        ["pytest", "--force"],
    ):
        with pytest.raises(ValueError):
            commands.validate(argv)


def test_argv_must_be_short_strings():
    with pytest.raises(ValueError):
        commands.validate([])
    with pytest.raises(ValueError):
        commands.validate(["python", "x" * 400])
    with pytest.raises(ValueError):
        commands.validate(["python", 42])


@pytest.mark.skipif(PYTHON is None, reason="no python interpreter available")
def test_request_then_approval_runs_argv(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "commands.sqlite3")
    pending = commands.request("demo", [PYTHON, "-c", "print('ok')"], "test run")
    assert pending["status"] == "pending"
    assert commands.pending("demo")[0]["request_id"] == pending["request_id"]

    with pytest.raises(HTTPException) as mismatch:
        commands.decide("demo", pending["request_id"], True, "0" * 64)
    assert mismatch.value.status_code == 409

    result = commands.decide("demo", pending["request_id"], True, pending["digest"])
    assert result["status"] == "succeeded"
    assert result["exit_code"] == 0
    assert "ok" in result["stdout"]

    with pytest.raises(HTTPException) as replay:
        commands.decide("demo", pending["request_id"], True, pending["digest"])
    assert replay.value.status_code == 409


@pytest.mark.skipif(PYTHON is None, reason="no python interpreter available")
def test_rejection_never_executes(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "commands.sqlite3")
    pending = commands.request("demo", [PYTHON, "-c", "print('should not run')"])
    result = commands.decide("demo", pending["request_id"], False, pending["digest"])
    assert result["status"] == "rejected"
    assert "stdout" not in result
    assert commands.pending("demo")[0]["status"] == "rejected"
