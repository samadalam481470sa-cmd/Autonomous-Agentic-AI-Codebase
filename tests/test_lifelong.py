"""Local lifelong learning: capture, rating, reranker promotion and RAG search."""
import json

import pytest
from fastapi.testclient import TestClient

from services.api import engine, lifelong, ranking, security, semantic
from services.api.main import app

TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("SEMANTIC_DIM", "96")
    monkeypatch.setenv("SEMANTIC_RAG", "0")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("LEARNING_STATE_PATH", str(tmp_path / "learning-state.sqlite3"))
    monkeypatch.setenv("AETHERION_LEARN_CAPTURE", "1")
    monkeypatch.setenv("AETHERION_LEARN_MIN_EXAMPLES", "1")
    monkeypatch.setenv("AETHERION_CONTINUOUS", "0")
    monkeypatch.setenv("AETHERION_AUTO_INDEX", "0")
    monkeypatch.delenv("AETHERION_LEARN_AC_ONLY", raising=False)
    security.reset()
    lifelong.MODEL_CACHE.clear()
    root = engine.workspace("demo")
    (root / "billing.py").write_text(
        "def calculate_invoice_total(items):\n    return sum(item.price for item in items)\n",
        encoding="utf-8",
    )
    (root / "auth.py").write_text(
        "import hashlib\n\ndef verify_password_hash(password, stored):\n"
        "    return hashlib.sha256(password.encode()).hexdigest() == stored\n",
        encoding="utf-8",
    )
    (root / "router.py").write_text(
        "def register_invoice_routes(app):\n    app.get('/invoices', list_invoices)\n",
        encoding="utf-8",
    )
    (root / "utils.py").write_text(
        "def format_currency(value):\n    return f'${value:.2f}'\n",
        encoding="utf-8",
    )
    semantic.index_project("demo")
    return root


def test_capture_redacts_secrets_and_rates(project):
    secret = "sk-" + "a" * 24
    ident = lifelong.capture(
        "demo", "ask", f"Use {secret} for the API", f"Answer contains {secret}",
        [{"path": "billing.py", "line": 1}],
    )
    assert ident
    rows = lifelong.interactions("demo")
    assert rows[0]["id"] == ident
    assert secret not in rows[0]["prompt"]
    assert secret not in rows[0]["response"]
    assert "[REDACTED:" in rows[0]["prompt"]
    assert rows[0]["redactions"] >= 2
    assert lifelong.rate("demo", ident, "up")["rated"]
    assert lifelong.interactions("demo")[0]["rating"] == "up"
    with pytest.raises(ValueError):
        lifelong.rate("demo", ident, "maybe")


def test_capture_can_be_disabled(project, monkeypatch):
    monkeypatch.setenv("AETHERION_LEARN_CAPTURE", "0")
    assert lifelong.capture("demo", "chat", "hello", "world") is None
    assert lifelong.interactions("demo") == []


def test_training_promotes_and_rolls_back(project):
    ranking.record("demo", "invoice total", "billing.py", 1, "up")
    ranking.record("demo", "invoice total", "auth.py", 1, "down")
    ranking.record("demo", "password hash", "auth.py", 1, "up")
    ranking.record("demo", "password hash", "billing.py", 1, "down")
    first = lifelong.train("demo", force=True)
    assert first["trained"]
    assert first["promoted"]
    assert lifelong.active_weights("demo") is not None
    second = lifelong.train("demo", force=True)
    assert second["trained"]
    rolled = lifelong.rollback("demo")
    assert rolled["rolled_back"]
    assert rolled["active_model"] == first["model_id"]


def test_training_requires_feedback(project):
    result = lifelong.train("demo")
    assert not result["trained"]
    assert result["reason"] == "not_enough_feedback"


def test_rag_search_endpoint_returns_context(project):
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    response = client.post(
        "/api/ai/search",
        json={"project": "demo", "query": "invoice total", "rag": True},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]
    assert payload["rag"]["citations"]
    assert payload["rag"]["text"].startswith("<untrusted_repository_context>")
    assert "learned_rerank" in payload["retrieval"]


def test_learning_status_and_interaction_rating_api(project):
    ident = lifelong.capture(
        "demo", "ask", "Where is billing?", "billing.py:1", [{"path": "billing.py", "line": 1}]
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.get("/api/learning/continuous/status").status_code == 403
    status = client.get(
        f"/api/learning/continuous/status?project=demo", headers=headers
    )
    assert status.status_code == 200
    assert status.json()["project"]["interactions"] == 1
    rated = client.post(
        f"/api/learning/demo/interactions/{ident}/rate",
        json={"project": "demo", "rating": "up"},
        headers=headers,
    )
    assert rated.status_code == 200
    assert rated.json()["rating"] == "up"


def test_background_tick_obeys_kill_switch(project, monkeypatch):
    lifelong.state_set("enabled", "0")
    assert lifelong.tick()["ran"] is False
    lifelong.state_set("enabled", "1")
    lifelong.state_set("paused", "1")
    assert lifelong.tick()["ran"] is False
    lifelong.state_set("paused", "0")
    monkeypatch.setenv("AETHERION_AUTO_INDEX", "0")
    result = lifelong.tick()
    assert result["ran"] is True
    assert result["projects"] >= 1


def test_status_records_privacy_and_model_shape(project):
    data = lifelong.status("demo")
    assert data["capture"] is True
    assert "locally" in data["privacy"]
    assert "models" in data
    assert json.dumps(data)  # response is JSON serialisable
