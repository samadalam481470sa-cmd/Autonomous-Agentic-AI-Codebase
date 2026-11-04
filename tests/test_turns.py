"""A whole assistant turn can be reverted, and a stale undo never overwrites."""
import pytest
from fastapi import HTTPException

from services.api import engine, studio, turns

TOKEN = "Bearer test-token-1234567890"


def setup_project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "test-token-1234567890")
    root = engine.workspace("demo")
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    return root


def apply_change(path, content):
    change = studio.ChangeRequest(project="demo", path=path, content=content)
    reviewed = studio.diff(change, authorization=TOKEN)
    change.expected_sha256 = reviewed["sha256"]
    return studio.apply(change, authorization=TOKEN, x_confirm_change="approve")


def test_apply_records_a_turn_and_revert_restores_it(tmp_path, monkeypatch):
    root = setup_project(tmp_path, monkeypatch)
    applied = apply_change("app.py", "value = 2\n")
    assert applied["turn_id"]
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 2\n"
    listing = turns.recent("demo")
    assert listing[0]["turn_id"] == applied["turn_id"]
    assert listing[0]["paths"] == ["app.py"]

    result = turns.revert("demo")
    assert result["files_reverted"] == 1
    assert result["skipped"] == []
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 1\n"


def test_revert_creates_its_own_undo_checkpoint(tmp_path, monkeypatch):
    root = setup_project(tmp_path, monkeypatch)
    applied = apply_change("app.py", "value = 2\n")
    result = turns.revert("demo", applied["turn_id"])
    assert result["reverted"][0]["undo_checkpoint_id"]
    history = studio.checkpoints.recent("demo", "app.py")
    assert len(history) >= 2


def test_new_file_turn_revert_deletes_the_file(tmp_path, monkeypatch):
    root = setup_project(tmp_path, monkeypatch)
    apply_change("created.py", "print('new')\n")
    assert (root / "created.py").is_file()
    turns.revert("demo")
    assert not (root / "created.py").exists()


def test_stale_undo_skips_a_file_changed_after_the_turn(tmp_path, monkeypatch):
    root = setup_project(tmp_path, monkeypatch)
    apply_change("app.py", "value = 2\n")
    (root / "app.py").write_text("manual edit\n", encoding="utf-8")
    result = turns.revert("demo")
    assert result["files_reverted"] == 0
    assert result["skipped"][0]["reason"] == "changed since the edit"
    assert (root / "app.py").read_text(encoding="utf-8") == "manual edit\n"


def test_revert_without_any_turn_is_not_found(tmp_path, monkeypatch):
    setup_project(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as error:
        turns.revert("demo")
    assert error.value.status_code == 404
