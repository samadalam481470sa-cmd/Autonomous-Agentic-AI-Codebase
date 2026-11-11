"""Git worktree isolation for agent runs."""
import os
import subprocess
from pathlib import Path

import pytest

from services.api import worktrees


def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True, env=env)
    return root


def test_create_changes_and_remove_worktree(tmp_path):
    root = repo(tmp_path)
    destination = tmp_path / "worktrees"
    created = worktrees.create(root, "b" * 32, override=destination)
    path = Path(created["path"])
    assert path.is_dir()
    assert created["branch"].startswith("agentic/run-")
    (path / "app.py").write_text("value = 2\n", encoding="utf-8")
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    state = worktrees.changes(path)
    assert state["clean"] is False
    assert "app.py" in state["files"]
    listed = worktrees.list_worktrees(root, override=destination)
    assert any(item["run_id"] == "b" * 32 for item in listed)
    worktrees.remove(root, path, override=destination)
    assert not path.exists()


def test_duplicate_and_invalid_run_ids_are_rejected(tmp_path):
    root = repo(tmp_path)
    destination = tmp_path / "worktrees"
    worktrees.create(root, "c" * 32, override=destination)
    with pytest.raises(ValueError, match="already exists"):
        worktrees.create(root, "c" * 32, override=destination)
    with pytest.raises(ValueError):
        worktrees.create(root, "../escape", override=destination)


def test_remove_refuses_paths_outside_the_root(tmp_path):
    root = repo(tmp_path)
    destination = tmp_path / "worktrees"
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="outside"):
        worktrees.remove(root, outside, override=destination)


def test_non_git_directory_is_rejected(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ValueError, match="git repository"):
        worktrees.create(plain, "d" * 32, override=tmp_path / "worktrees")
