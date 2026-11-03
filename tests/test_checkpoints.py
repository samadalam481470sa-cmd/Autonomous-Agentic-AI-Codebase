"""Durable checkpoints: existing file, new file, batch, stale state and authorization."""
import hashlib
import pytest
from fastapi import HTTPException
from services.api import engine, checkpoints, studio, multi_file_agent as batch

AUTH = "Bearer test-token"

def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path/"workspace")
    monkeypatch.setattr(engine,"DB",tmp_path/"history.sqlite")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-token")
    return engine.workspace("demo")

def edit(path, content):
    proposal=studio.ChangeRequest(project="demo",path=path,content=content)
    proposed=studio.diff(proposal,authorization=AUTH)
    proposal.expected_sha256=proposed["sha256"]
    return studio.apply(proposal,authorization=AUTH,x_confirm_change="approve")

def restore(path, checkpoint, current_text, approve="approve", expected=None):
    return studio.restore_checkpoint(
        studio.RestoreRequest(project="demo",path=path,
            checkpoint_id=checkpoint,
            expected_sha256=expected or studio.digest(current_text)),
        authorization=AUTH,x_confirm_change=approve)

def test_existing_file_can_restore_and_reapply(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch)
    p=root/"main.py"
    p.write_text("value = 1\n")
    result=edit("main.py","value = 2\n")
    assert p.read_text()=="value = 2\n"
    history=studio.checkpoints_for_file(
        studio.FileRequest(project="demo",path="main.py"),authorization=AUTH
    )["checkpoints"]
    assert history[0]["id"]==result["checkpoint_id"]
    rollback=restore("main.py",result["checkpoint_id"],"value = 2\n")
    assert p.read_text()=="value = 1\n"
    restore("main.py",rollback["undo_checkpoint_id"],"value = 1\n")
    assert p.read_text()=="value = 2\n"

def test_new_file_checkpoint_removes_and_undo_restores(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch)
    result=edit("created.txt","new contents")
    p=root/"created.txt"
    assert p.is_file()
    undo=restore("created.txt",result["checkpoint_id"],"new contents")
    assert undo["exists"] is False
    assert not p.exists()
    restore("created.txt",undo["undo_checkpoint_id"],"")
    assert p.read_text()=="new contents"

def test_stale_checkpoint_or_bad_expected_hash_cannot_overwrite(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch)
    p=root/"safe.py"
    p.write_text("before")
    change=edit("safe.py","after")
    p.write_text("external edit")
    with pytest.raises(HTTPException) as caught:
        restore("safe.py",change["checkpoint_id"],"external edit")
    assert caught.value.status_code==409
    assert p.read_text()=="external edit"
    p.write_text("after")
    with pytest.raises(HTTPException) as caught:
        restore("safe.py",change["checkpoint_id"],"WRONG")
    assert caught.value.status_code==409

def test_restore_requires_explicit_approval(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    result=edit("safe.py","after")
    with pytest.raises(HTTPException) as caught:
        restore("safe.py",result["checkpoint_id"],"after",approve=None)
    assert caught.value.status_code==428

def test_metadata_nested_paths_and_symlinks_refused(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch)
    (root/"src").mkdir()
    try:
        (root/"src"/"private").symlink_to(root)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation requires elevated privileges on this platform")
    for path in ("src/.agent/a.json","src/.git/config","../escape.txt","src/private/a.txt"):
        with pytest.raises(HTTPException):
            studio.resolve("demo",path)

def test_batch_save_checkpoints_per_file(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch)
    changes=[]
    for path in ("alpha.py","beta.py"):
        (root/path).write_text("old\n")
        changes.append({"path":path,"content":"new\n",
            "expected_sha256":studio.digest("old\n"),"diff":"test"})
    record=batch.create_record("demo",changes)
    result=batch.apply_record("demo",record["proposal_id"],record["proposal_hash"])
    assert len(result["checkpoint_ids"])==2
    for path,checkpoint_id in zip(("alpha.py","beta.py"),result["checkpoint_ids"]):
        restore(path,checkpoint_id,"new\n")
        assert (root/path).read_text()=="old\n"

def test_checkpoints_survive_sqlite_reopen(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    change=edit("persist.md","hello")
    assert checkpoints.one("demo","persist.md",change["checkpoint_id"])["previous_exists"]==0
    with engine.db() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM file_checkpoints"
        ).fetchone()[0]==1

def test_restore_does_not_expose_other_project_checkpoint(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    result=edit("a.txt","hello")
    with pytest.raises(HTTPException) as caught:
        studio.restore_checkpoint(
            studio.RestoreRequest(project="other",path="a.txt",
                checkpoint_id=result["checkpoint_id"],
                expected_sha256=studio.digest("")),
            authorization=AUTH,x_confirm_change="approve"
        )
    assert caught.value.status_code==404
