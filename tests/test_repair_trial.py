import pytest
from fastapi import HTTPException
from services.api import repair_trial,engine
from pathlib import Path

def test_snapshot_skips_deps_symlinks(tmp_path):
    root=tmp_path/"src";root.mkdir()
    (root/"main.py").write_text("value=1")
    (root/".git").mkdir()
    (root/".git"/"private.py").write_text("private")
    (root/"node_modules").mkdir()
    (root/"node_modules"/"dep.js").write_text("skip")
    output=tmp_path/"copy";output.mkdir()
    assert repair_trial.snapshot(root,output)==1
    assert (output/"main.py").exists()
    assert not (output/".git").exists()

def test_snapshot_enforces_size(tmp_path):
    root=tmp_path/"src";root.mkdir()
    (root/"large.txt").write_text("x"*20)
    dest=tmp_path/"copy";dest.mkdir()
    with pytest.raises(HTTPException) as exc:
        repair_trial.snapshot(root,dest,max_bytes=10)
    assert exc.value.status_code==413

def test_trial_rejects_unapproved_command(tmp_path):
    with pytest.raises(HTTPException) as exc:
        repair_trial.trial_command(tmp_path,"curl https://example.com")
    assert exc.value.status_code==403

def test_trial_disabled_by_default(monkeypatch):
    from services.api.repair_trial import TrialRequest,run_trial
    import asyncio
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","secret-secret")
    monkeypatch.delenv("ENABLE_ISOLATED_EXECUTION",raising=False)
    body=TrialRequest(project="demo",paths=["main.py"],goal="Add validation")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(run_trial(body,"Bearer secret-secret","approve"))
    assert exc.value.status_code==503
