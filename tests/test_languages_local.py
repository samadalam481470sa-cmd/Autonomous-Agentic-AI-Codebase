import pytest
from services.api.languages import identify,LANGUAGES
from services.api.local_model import local_url
def test_language_detection():
    assert identify("src/index.tsx")=="typescript"
    assert identify("db/schema.sql")=="sql"
    assert identify("Dockerfile")=="dockerfile"
    assert identify("unknown.xyz")=="plaintext"
def test_language_registry():
    assert len(LANGUAGES)>=45
def test_local_url(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_BASE_URL","http://127.0.0.1:11434/v1")
    assert local_url()=="http://127.0.0.1:11434/v1"
@pytest.mark.parametrize("url",["https://api.openai.com/v1","http://evil.example/v1","http://127.0.0.1.evil.com/v1","file:///tmp/model","http://user:pass@localhost:11434/v1"])
def test_local_rejects_remote(monkeypatch,url):
    monkeypatch.setenv("LOCAL_MODEL_BASE_URL",url)
    with pytest.raises(ValueError):local_url()
