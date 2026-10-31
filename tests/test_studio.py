import hashlib
import pytest
from fastapi import HTTPException
from services.api import engine
from services.api.studio import authorize,resolve,current,digest,FileRequest,ChangeRequest,apply,diff,read

def test_token_required(monkeypatch):
    monkeypatch.delenv("AGENT_ADMIN_TOKEN",raising=False)
    with pytest.raises(HTTPException) as e:authorize("Bearer test")
    assert e.value.status_code==403

def test_path_restrictions(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    for path in ["../outside",".agent/plan.json",".git/config"]:
        with pytest.raises(HTTPException):resolve("demo",path)

def test_diff_then_approval(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-token")
    b=ChangeRequest(project="demo",path="index.html",content="<h1>hello</h1>")
    d=diff(b,authorization="Bearer test-token")
    assert d["changed"] and "+<h1>hello</h1>" in d["diff"]
    b.expected_sha256=d["sha256"]
    with pytest.raises(HTTPException) as e:apply(b,authorization="Bearer test-token",x_confirm_change=None)
    assert e.value.status_code==428
    result=apply(b,authorization="Bearer test-token",x_confirm_change="approve")
    assert result["saved"]
    assert read(FileRequest(project="demo",path="index.html"),authorization="Bearer test-token")["content"]=="<h1>hello</h1>"
    with pytest.raises(HTTPException) as e:apply(b,authorization="Bearer test-token",x_confirm_change="approve")
    assert e.value.status_code==409
