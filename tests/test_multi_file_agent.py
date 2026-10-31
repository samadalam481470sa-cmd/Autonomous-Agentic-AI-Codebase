import json
import pytest
from fastapi import HTTPException
from services.api import engine,multi_file_agent as batch

def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    root=engine.workspace("demo")
    (root/"one.py").write_text("value = 1\n")
    (root/"two.py").write_text("other = 1\n")
    return root

def test_atomic_batch_apply(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch)
    changes=[]
    for name,old,new in [("one.py","value = 1\n","value = 2\n"),("two.py","other = 1\n","other = 2\n")]:
        changes.append({"path":name,"expected_sha256":batch.digest(old),"content":new,"diff":"test"})
    result=batch.create_record("demo",changes)
    assert (root/"one.py").read_text()=="value = 1\n"
    assert (root/"two.py").read_text()=="other = 1\n"
    with pytest.raises(HTTPException) as denied:
        batch.apply_batch(batch.ApplyRequest(project="demo",proposal_id=result["proposal_id"],
            proposal_hash=result["proposal_hash"]),None,None)
    assert denied.value.status_code==403
    applied=batch.apply_record("demo",result["proposal_id"],result["proposal_hash"])
    assert applied["applied"]==2
    assert (root/"one.py").read_text()=="value = 2\n"
    assert (root/"two.py").read_text()=="other = 2\n"
    with pytest.raises(HTTPException) as duplicate:
        batch.apply_record("demo",result["proposal_id"],result["proposal_hash"])
    assert duplicate.value.status_code==409

def test_stale_file_prevents_all_writes(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch)
    changes=[{"path":x,"expected_sha256":batch.digest((root/x).read_text()),"content":"new = 10\n","diff":"diff"}
        for x in ("one.py","two.py")]
    proposal=batch.create_record("demo",changes)
    (root/"two.py").write_text("someone else edited\n")
    with pytest.raises(HTTPException) as conflict:
        batch.apply_record("demo",proposal["proposal_id"],proposal["proposal_hash"])
    assert conflict.value.status_code==409
    assert (root/"one.py").read_text()=="value = 1\n"

def test_reject_duplicate_and_metadata_paths(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    for paths in (["one.py","one.py"],[".agent/private.py"]):
        with pytest.raises(HTTPException):
            batch.check_paths("demo",paths)
