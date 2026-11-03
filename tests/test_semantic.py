"""Local embedding index, hybrid retrieval, RAG context and AI endpoints."""
import pytest
from fastapi.testclient import TestClient

from services.api import engine, security, semantic
from services.api import ai_features
from services.api.main import app

TOKEN = "correct-horse-battery-staple"

BILLING = (
    "def calculate_invoice_total(items):\n"
    "    subtotal = 0\n"
    "    for item in items:\n"
    "        subtotal += item.price * item.quantity\n"
    "    return subtotal\n"
)
AUTH = (
    "import hashlib\n\n"
    "def verify_password_hash(password, stored_digest):\n"
    "    digest = hashlib.sha256(password.encode()).hexdigest()\n"
    "    return digest == stored_digest\n"
)
ROUTER = (
    "def register_invoice_routes(app):\n"
    "    app.get('/invoices', list_invoices)\n"
    "    app.post('/invoices', create_invoice)\n"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("SEMANTIC_DIM", "128")
    monkeypatch.setenv("SEMANTIC_RAG", "0")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_MODEL_ONLY", raising=False)
    security.reset()
    root = engine.workspace("demo")
    (root / "billing.py").write_text(BILLING, encoding="utf-8")
    (root / "auth.py").write_text(AUTH, encoding="utf-8")
    (root / "router.py").write_text(ROUTER, encoding="utf-8")
    return root


def test_index_is_incremental_and_reports_vectors(project):
    first = semantic.index_project("demo")
    assert first["embedded_files"] == 3
    assert first["vectors"] >= 3
    assert first["dimensions"] == 128
    second = semantic.index_project("demo")
    assert second["embedded_files"] == 0
    assert second["unchanged_files"] == 3
    assert second["removed_files"] == 0
    assert second["vectors"] == first["vectors"]


def test_semantic_search_ranks_relevant_file(project):
    semantic.index_project("demo")
    results = semantic.search("demo", "calculate invoice total", mode="semantic")
    assert results
    assert results[0]["path"] == "billing.py"
    assert "semantic" in results[0]["sources"]


def test_identifier_splitting_matches_without_exact_words(project):
    semantic.index_project("demo")
    results = semantic.search("demo", "password digest verification", mode="semantic")
    assert results
    assert results[0]["path"] == "auth.py"


def test_hybrid_search_fuses_lexical_matches(project):
    semantic.index_project("demo")
    results = semantic.search("demo", "create_invoice", mode="hybrid")
    assert results
    paths = [item["path"] for item in results]
    assert "router.py" in paths
    assert any("lexical" in item["sources"] for item in results)


def test_reindex_removes_stale_content(project):
    semantic.index_project("demo")
    (project / "billing.py").write_text(
        "def refund_credit_card(transaction):\n    return transaction.amount\n", encoding="utf-8"
    )
    report = semantic.index_project("demo")
    assert report["embedded_files"] == 1
    with semantic._db("demo") as con:
        bodies = [row[0] for row in con.execute("SELECT body FROM sem_vectors")]
    assert all("calculate_invoice_total" not in body for body in bodies)
    stale = semantic.search("demo", "calculate invoice total", mode="semantic")
    assert not stale or stale[0]["path"] != "billing.py"
    assert semantic.search("demo", "refund credit card", mode="semantic")[0]["path"] == "billing.py"


def test_projects_are_isolated(project):
    semantic.index_project("demo")
    other = engine.workspace("other")
    (other / "notes.py").write_text("def unrelated_helper():\n    return 1\n", encoding="utf-8")
    semantic.index_project("other")
    assert semantic.search("other", "invoice total", mode="hybrid") == []


def test_context_is_budgeted_and_wrapped(project):
    semantic.index_project("demo")
    context = semantic.context("demo", "invoice total", budget_chars=400, max_files=2)
    assert context["text"].startswith("<untrusted_repository_context>")
    assert context["text"].endswith("</untrusted_repository_context>")
    assert context["used_chars"] <= 400
    assert context["citations"]
    assert all("path" in item and "line" in item for item in context["citations"])


def test_similar_files_and_stats(project):
    semantic.index_project("demo")
    related = semantic.similar("demo", "billing.py", limit=5)
    assert related
    assert all(item["path"] != "billing.py" for item in related)
    stats = semantic.stats("demo")
    assert stats["indexed_files"] == 3
    assert stats["model"] == semantic.EMBEDDING_MODEL
    assert stats["dimensions"] == 128


def test_ai_endpoints_require_auth_and_serve_results(project):
    client = TestClient(app)
    body = {"project": "demo", "query": "invoice"}
    assert client.post("/api/ai/search", json=body).status_code == 403
    headers = {"Authorization": "Bearer " + TOKEN}
    indexed = client.post("/api/ai/index/refresh", json={"project": "demo"}, headers=headers)
    assert indexed.status_code == 200
    found = client.post("/api/ai/search", json=body, headers=headers)
    assert found.status_code == 200
    assert found.json()["results"]
    assert client.get("/api/ai/demo/stats", headers=headers).status_code == 200


def test_ask_uses_retrieved_untrusted_context(project, monkeypatch):
    semantic.index_project("demo")
    captured = {}

    async def fake_complete(system, user, max_tokens):
        captured["system"] = system
        captured["user"] = user
        return "Invoice totals are computed in billing.py:1"

    monkeypatch.setattr(ai_features, "_complete", fake_complete)
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    response = client.post("/api/ai/ask", json={"project": "demo", "question": "where are invoice totals computed"},
                           headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["citations"]
    assert "untrusted_repository_context" in captured["user"]
    assert "billing.py" in payload["answer"]


def test_ask_without_matches_does_not_call_model(project, monkeypatch):
    async def explode(system, user, max_tokens):
        raise AssertionError("model must not be called without retrieved context")

    monkeypatch.setattr(ai_features, "_complete", explode)
    client = TestClient(app)
    response = client.post("/api/ai/ask", json={"project": "demo", "question": "quantum entanglement"},
                           headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 200
    assert response.json()["citations"] == []
