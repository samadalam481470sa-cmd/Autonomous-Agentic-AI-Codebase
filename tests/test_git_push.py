"""Pushing from the app is opt-in, branch-scoped and never forced."""
import subprocess

import pytest
from fastapi import HTTPException

from services.api import gitflow


def _git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


def _repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-m", "init")
    return path


def test_push_needs_explicit_opt_in(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    monkeypatch.delenv("GIT_ALLOW_PUSH", raising=False)
    with pytest.raises(HTTPException) as caught:
        gitflow.push(repo)
    assert caught.value.status_code == 503


def test_push_refuses_without_a_remote(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    monkeypatch.setenv("GIT_ALLOW_PUSH", "1")
    with pytest.raises(HTTPException) as caught:
        gitflow.push(repo)
    assert caught.value.status_code == 400


def test_push_sends_the_current_branch_to_origin(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "switch", "-c", "feature/smoke")
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "add b")
    monkeypatch.setenv("GIT_ALLOW_PUSH", "1")
    result = gitflow.push(repo)
    assert result["pushed"] is True
    assert result["branch"] == "feature/smoke"
    ref = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "feature/smoke"],
                         capture_output=True, text=True)
    assert ref.returncode == 0
    assert ref.stdout.strip() == result["head"].strip()
