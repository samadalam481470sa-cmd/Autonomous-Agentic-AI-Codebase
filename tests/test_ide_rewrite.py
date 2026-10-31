"""Local model rewrite never writes files or calls a cloud endpoint."""
import asyncio
import hashlib
import httpx
import pytest
from fastapi import HTTPException
from services.api import ide_rewrite

def run(monkeypatch,response,auth="Bearer test-token"):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-token")
    monkeypatch.setenv("LOCAL_MODEL_ONLY","1")
    monkeypatch.setenv("LOCAL_MODEL_BASE_URL","http://127.0.0.1:8088/v1")
    monkeypatch.setenv("LOCAL_MODEL_NAME","coder")
    calls=[]
    def handler(request):
        calls.append(request)
        return response
    factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),trust_env=False)
    body=ide_rewrite.RewriteRequest(language="python",selection="print(1)",instruction="Change the output")
    result=asyncio.run(ide_rewrite.rewrite_selection(body,auth,factory))
    return result,calls

def test_model_rewrite_returns_approval_gated_text(monkeypatch):
    response=httpx.Response(200,json={"choices":[{"message":{"content":"print(2)"}}]})
    result,calls=run(monkeypatch,response)
    assert result["changed"] and result["requires_approval"]
    assert result["source_sha256"]==hashlib.sha256(b"print(1)").hexdigest()
    assert result["content"]=="print(2)"
    assert str(calls[0].url)=="http://127.0.0.1:8088/v1/chat/completions"
    assert calls[0].headers["Authorization"]=="Bearer local"
    assert b'"tool_choice":"none"' in calls[0].content

def test_remote_upstream_forbidden(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_ONLY","1")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-token")
    monkeypatch.setenv("LOCAL_MODEL_BASE_URL","https://cloud.example.com/v1")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ide_rewrite.rewrite_selection(ide_rewrite.RewriteRequest(
            language="python",selection="a",instruction="Rewrite code"),"Bearer test-token"))
    assert exc.value.status_code==503

def test_requires_local_mode_and_authentication(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_ONLY","0")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-token")
    body=ide_rewrite.RewriteRequest(language="python",selection="x",instruction="Rewrite code")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ide_rewrite.rewrite_selection(body,"Bearer test-token"))
    assert exc.value.status_code==409
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ide_rewrite.rewrite_selection(body,"Bearer bad"))
    assert exc.value.status_code==403

def test_model_errors_do_not_produce_edits(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        run(monkeypatch,httpx.Response(502,json={"error":"offline"}))
    assert exc.value.status_code==502

@pytest.mark.parametrize("suggestion",["","  ","x"*50001])
def test_empty_and_oversized_rewrites_refused(suggestion):
    with pytest.raises(HTTPException) as exc:
        ide_rewrite.response_for("a",suggestion)
    assert exc.value.status_code==502

@pytest.mark.parametrize("selection,lang,instruction",[
    ("","python","Fix this"),
    ("a","<script>","Fix this"),
    ("a","python","bad"),
    ("a"*12001,"python","Fix this")
])
def test_selection_limits(selection,lang,instruction):
    with pytest.raises(Exception):
        ide_rewrite.RewriteRequest(selection=selection,language=lang,instruction=instruction)
