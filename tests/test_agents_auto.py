"""Bounded auto-advance for multi-agent runs."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from services.api import engine, orchestrator, security
from services.api.main import app

TOKEN = "auto-run-token-123456789"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("ORCHESTRATOR_DB_PATH", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setenv("EVENT_DB_PATH", str(tmp_path / "events.sqlite3"))
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("SEMANTIC_RAG", "0")
    monkeypatch.setenv("DEVICE_THERMAL_GUARD", "0")
    security.reset()
    engine.workspace("demo")
    return tmp_path


async def fake_complete(system, user, max_tokens=1200):
    return "bounded auto step"


def test_auto_run_finishes_all_steps(project, monkeypatch):
    monkeypatch.setattr(orchestrator, "_complete", fake_complete)
    run = orchestrator.create_run("demo", "Implement a health endpoint")
    result = asyncio.run(orchestrator.run_to_completion(run["id"], max_steps=8))
    assert result["status"] == "completed"
    assert result["progress"] == {"completed": 5, "total": 5}
    assert result["auto"]["steps_run"] == 5
    assert result["auto"]["stopped"] == "terminal"


def test_auto_run_respects_step_limit(project, monkeypatch):
    monkeypatch.setattr(orchestrator, "_complete", fake_complete)
    run = orchestrator.create_run("demo", "Implement a health endpoint")
    result = asyncio.run(orchestrator.run_to_completion(run["id"], max_steps=2))
    assert result["progress"]["completed"] == 2
    assert result["auto"]["steps_run"] == 2
    assert result["auto"]["stopped"] == "step_limit"


def test_auto_run_returns_blocked_state(project, monkeypatch):
    async def failing(system, user, max_tokens=1200):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(orchestrator, "_complete", failing)
    run = orchestrator.create_run("demo", "Implement a health endpoint")
    result = asyncio.run(orchestrator.run_to_completion(run["id"], max_steps=8))
    assert result["status"] == "blocked"
    assert result["auto"]["status_code"] == 502


def test_auto_advance_endpoint(project, monkeypatch):
    monkeypatch.setattr(orchestrator, "_complete", fake_complete)
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    created = client.post(
        "/api/agents/runs",
        json={"project": "demo", "goal": "Implement a health endpoint"},
        headers=headers,
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    response = client.post(
        f"/api/agents/runs/{run_id}/auto-advance",
        json={"max_steps": 8},
        headers=headers,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "completed"
    assert result["auto"]["steps_run"] == 5
