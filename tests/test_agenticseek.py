import pytest
from services.api.agenticseek import config,AgenticSeekUnavailable
from services.api.agents import plan,load
from services.api import engine

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AGENTICSEEK_URL",raising=False)
    monkeypatch.delenv("AGENTICSEEK_API_TOKEN",raising=False)
    with pytest.raises(AgenticSeekUnavailable):config()

@pytest.mark.parametrize("url",["https://evil.example","http://127.0.0.1.evil.example","http://user:pass@localhost:8000","file:///etc/passwd","http://localhost:8000/path"])
def test_reject_unsafe_addresses(monkeypatch,url):
    monkeypatch.setenv("AGENTICSEEK_URL",url)
    monkeypatch.setenv("AGENTICSEEK_API_TOKEN","test")
    with pytest.raises(AgenticSeekUnavailable):config()

def test_local_config(monkeypatch):
    monkeypatch.setenv("AGENTICSEEK_URL","http://127.0.0.1:8000")
    monkeypatch.setenv("AGENTICSEEK_API_TOKEN","test")
    assert config()==("http://127.0.0.1:8000","test")

def test_plan_persists(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    p=plan("demo","Build a dashboard")
    assert p["status"]=="draft"
    assert [x["role"] for x in load("demo")["tasks"]]==["architect","coder","reviewer"]
