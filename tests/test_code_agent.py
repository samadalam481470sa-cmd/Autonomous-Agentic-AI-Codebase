import pytest
from fastapi import HTTPException
from services.api import code_agent,engine

def test_proposal_returns_reviewable_diff_without_writes(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    root=tmp_path/"demo"
    root.mkdir()
    existing=root/"main.py"
    existing.write_text("value = 1\n",encoding="utf-8")
    old=existing.read_text()
    result=code_agent.proposal_for("main.py",old,"value = 2\n")
    assert result["changed"]
    assert result["requires_approval"]
    assert "-value = 1" in result["diff"]
    assert "+value = 2" in result["diff"]
    assert result["expected_sha256"]==code_agent.digest(old)
    assert existing.read_text()==old

def test_code_proposal_rejects_empty_and_large():
    with pytest.raises(HTTPException) as empty:
        code_agent.proposal_for("a.py","x=1","")
    assert empty.value.status_code==502
    with pytest.raises(HTTPException):
        code_agent.proposal_for("a.py","", "x"*(code_agent.MAX_RESPONSE_CHARS+1))

def test_proposal_authorization_requires_token(monkeypatch):
    monkeypatch.delenv("AGENT_ADMIN_TOKEN",raising=False)
    with pytest.raises(HTTPException) as denied:
        code_agent.authorize(None)
    assert denied.value.status_code==403
