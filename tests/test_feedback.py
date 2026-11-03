"""Feedback-driven re-ranking of local retrieval results."""
import pytest
from fastapi.testclient import TestClient

from services.api import engine, ranking, security, semantic
from services.api.main import app

TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("SEMANTIC_DIM", "128")
    monkeypatch.setenv("SEMANTIC_RAG", "0")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.delenv("AGENT_TOTP_SECRET", raising=False)
    security.reset()
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
    (root / "utils.py").write_text(
        "def verify_password_digest(password_digest):\n    return password_digest\n",
        encoding="utf-8",
    )
    return root


def test_feedback_learning_reorders_results(project, monkeypatch):
    monkeypatch.setenv("SEMANTIC_FEEDBACK_WEIGHT", "0.08")
    semantic.index_project("demo")
    baseline = semantic.search("demo", "password digest verification", mode="hybrid", limit=5)
    assert len(baseline) >= 2
    demote = baseline[0]
    promote = next((item for item in baseline if item["path"] != demote["path"]), None)
    assert promote is not None
    for _ in range(5):
        ranking.record("demo", "password", promote["path"], promote["line"], "up")
        ranking.record("demo", "password", demote["path"], demote["line"], "down")
    reordered = semantic.search("demo", "password digest verification", mode="hybrid", limit=5)
    assert reordered[0]["path"] == promote["path"]
    assert reordered[0]["learned_boost"] > 0
    summary = ranking.summary("demo")
    assert summary["positive"] == 5
    assert summary["negative"] == 5
    assert summary["paths"] >= 1


def test_feedback_is_disabled_when_weight_is_zero(project, monkeypatch):
    monkeypatch.setenv("SEMANTIC_FEEDBACK_WEIGHT", "0")
    semantic.index_project("demo")
    ranking.record("demo", "invoice", "billing.py", 1, "up")
    results = semantic.search("demo", "invoice total", mode="hybrid")
    assert results
    assert all("learned_boost" not in item for item in results)


def test_feedback_rejects_unknown_paths_and_ratings(project):
    with pytest.raises(ValueError):
        ranking.record("demo", "query", "../outside", 1, "up")
    with pytest.raises(ValueError):
        ranking.record("demo", "query", "missing.py", 1, "up")
    with pytest.raises(ValueError):
        ranking.record("demo", "query", "billing.py", 1, "maybe")


def test_feedback_endpoints_record_and_report(project):
    semantic.index_project("demo")
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    body = {"project": "demo", "query": "invoice", "path": "billing.py",
            "line": 1, "rating": "up"}
    recorded = client.post("/api/ai/feedback", json=body, headers=headers)
    assert recorded.status_code == 200
    assert recorded.json()["ranking"]["positive"] == 1
    state = client.get("/api/ai/demo/ranking", headers=headers)
    assert state.status_code == 200
    assert state.json()["positive"] == 1
    assert client.post("/api/ai/feedback", json={**body, "path": "../escape"},
                       headers=headers).status_code == 400
    assert client.post("/api/ai/feedback", json={**body, "rating": "maybe"},
                       headers=headers).status_code == 422
    assert client.get("/api/ai/demo/ranking").status_code == 403
