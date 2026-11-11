"""Model selection is catalog-only and usage accounting stays local."""
import pytest

from services.api import engine, models


def test_catalog_always_lists_the_local_model(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_MODEL_NAME", "qwen2.5-coder:7b")
    ids = {item["id"] for item in models.catalog()}
    assert "local:qwen2.5-coder:7b" in ids
    publics = models.public_catalog()
    assert all("api_key" not in entry for entry in publics)
    assert all("api_key_env" not in entry for entry in publics)


def test_nothing_configured_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_MODEL_ONLY", raising=False)
    assert models.default_id() == ""
    with pytest.raises(ValueError) as error:
        models.resolve()
    assert "No model is configured" in str(error.value)


def test_local_only_resolves_the_loopback_endpoint(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_ONLY", "1")
    monkeypatch.setenv("LOCAL_MODEL_BASE_URL", "http://127.0.0.1:8088/v1")
    chosen = models.resolve()
    assert chosen["provider"] == "local"
    assert chosen["api_key"] == "local"
    assert chosen["base_url"] == "http://127.0.0.1:8088/v1"


def test_unknown_model_ids_are_rejected(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_ONLY", "1")
    for identifier in ("../../etc/passwd", "gpt-does-not-exist", "x" * 200):
        with pytest.raises(ValueError):
            models.resolve(identifier)


def test_hosted_selection_requires_its_key(monkeypatch):
    monkeypatch.delenv("LOCAL_MODEL_ONLY", raising=False)
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("MODEL_API_KEY", "secret-value")
    chosen = models.resolve()
    assert chosen["model"] == "test-model"
    assert chosen["api_key"] == "secret-value"
    monkeypatch.delenv("MODEL_API_KEY")
    with pytest.raises(ValueError):
        models.resolve()


def test_env_catalog_rejects_a_non_loopback_local_entry(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_ONLY", "1")
    monkeypatch.setenv("MODEL_CATALOG",
                       '[{"id":"evil","provider":"local",'
                       '"base_url":"http://evil.example/v1","model":"m"}]')
    ids = {item["id"] for item in models.catalog()}
    assert "evil" not in ids


def test_usage_is_estimated_and_stored_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DB", tmp_path / "usage.sqlite3")
    models.record_usage("demo", "local:test", 40, 8)
    models.record_usage("demo", "local:test", 4, 4)
    summary = models.usage_summary("demo")
    assert summary["calls"] == 2
    assert summary["prompt_tokens"] == 11
    assert summary["models"][0]["model"] == "local:test"
    assert summary["estimated"] is True
