"""Git operations stay local: no push, no force, explicit approval."""
import subprocess

import pytest
from fastapi import HTTPException

from services.api import engine, gitflow

ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.test",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.test",
}


def make_repo(tmp_path, monkeypatch):
    root = tmp_path / "workspaces" / "demo"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env={**__import__("os").environ, **ENV})
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True, env={**__import__("os").environ, **ENV})
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True, env={**__import__("os").environ, **ENV})
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    return root


def test_status_reports_branch_and_pending_changes(tmp_path, monkeypatch):
    root = make_repo(tmp_path, monkeypatch)
    (root / "app.py").write_text("value = 2\n", encoding="utf-8")
    data = gitflow.status(gitflow.repository("demo"))
    assert data["clean"] is False
    assert "app.py" in data["files"]
    assert data["recent_commits"][0].endswith("initial")


def test_branch_names_are_validated(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    for bad in ("../escape", "-flag", "a..b", "name.lock", "trailing/"):
        with pytest.raises(ValueError):
            gitflow.branch_name(bad)


def test_branch_creation_and_duplicate_refusal(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    repo = gitflow.repository("demo")
    assert gitflow.create_branch(repo, "feature/agent-loop")["created"] is True
    with pytest.raises(HTTPException) as conflict:
        gitflow.create_branch(repo, "feature/agent-loop")
    assert conflict.value.status_code == 409


def test_commit_requires_staged_changes(tmp_path, monkeypatch):
    root = make_repo(tmp_path, monkeypatch)
    repo = gitflow.repository("demo")
    with pytest.raises(HTTPException):
        gitflow.commit(repo, "empty commit", [])
    (root / "app.py").write_text("value = 2\n", encoding="utf-8")
    result = gitflow.commit(repo, "Update app value", ["app.py"])
    assert result["committed"] is True
    assert result["sha"]
    assert result["files"] == ["app.py"]


def test_commit_rejects_paths_outside_the_project(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    repo = gitflow.repository("demo")
    with pytest.raises(ValueError):
        gitflow.commit(repo, "escape attempt", ["../outside.py"])


def test_pull_request_preparation_never_pushes(tmp_path, monkeypatch):
    root = make_repo(tmp_path, monkeypatch)
    repo = gitflow.repository("demo")
    base = gitflow.status(repo)["branch"]
    gitflow.create_branch(repo, "feature/value")
    (root / "app.py").write_text("value = 3\n", encoding="utf-8")
    gitflow.commit(repo, "Change value", ["app.py"])
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
                   cwd=root, check=True, env={**__import__("os").environ, **ENV})
    data = gitflow.pull_request(repo, "Change value", base)
    assert data["pushed"] is False
    assert data["branch"] == "feature/value"
    assert data["compare_url"].startswith(
        "https://github.com/owner/repo/compare/" + base + "...feature/value")
    assert "Change value" in data["body"]
