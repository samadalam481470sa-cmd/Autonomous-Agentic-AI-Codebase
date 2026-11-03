"""Bounded multi-agent runs: planning, execution, durability and limits."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from services.api import engine, orchestrator, security
from services.api.main import app

TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("ORCHESTRATOR_DB_PATH", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.delenv("AGENT_TOTP_SECRET", raising=False)
    monkeypatch.setenv("SEMANTIC_RAG", "0")
    monkeypatch.setenv("DEVICE_THERMAL_GUARD", "0")
    security.reset()
    root = engine.workspace("demo")
    (root / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    return root


async def fake_complete(system, user, max_tokens=1200):
    assert "untrusted" in user.lower() or "Goal:" in user
    return "step output: inspect app.py:1"


def test_create_run_is_persisted_and_ordered(project):
    run = orchestrator.create_run("demo", "Add a health endpoint with tests")
    assert run["status"] == "queued"
    assert [step["role"] for step in run["steps"]] == [
        "architect", "coder", "tester", "security", "reviewer"
    ]
    assert run["progress"] == {"completed": 0, "total": 5}
    listed = orchestrator.list_runs("demo")
    assert listed[0]["id"] == run["id"]
    assert orchestrator.get_run(run["id"])["goal"].startswith("Add a health")


def test_plan_mode_uses_two_steps(project):
    run = orchestrator.create_run("demo", "Plan a checkout refactor", mode="plan")
    assert [step["role"] for step in run["steps"]] == ["architect", "reviewer"]
    with pytest.raises(ValueError):
        orchestrator.create_run("demo", "short")
    with pytest.raises(ValueError):
        orchestrator.create_run("demo", "A valid enough goal", mode="autonomous")


def test_advance_completes_each_step_in_order(project, monkeypatch):
    monkeypatch.setattr(orchestrator, "_complete", fake_complete)
    run = orchestrator.create_run("demo", "Implement a health endpoint")
    first = asyncio.run(orchestrator.advance_run(run["id"]))
    assert first["steps"][0]["status"] == "completed"
    assert first["steps"][0]["output"].startswith("step output")
    assert first["steps"][1]["status"] == "pending"
    assert first["progress"]["completed"] == 1
    for _ in range(4):
        result = asyncio.run(orchestrator.advance_run(run["id"]))
    assert result["status"] == "completed"
    assert result["progress"]["completed"] == 5
    assert asyncio.run(orchestrator.advance_run(run["id"]))["status"] == "completed"


def test_model_failure_blocks_and_can_be_retried(project, monkeypatch):
    async def failing(system, user, max_tokens=1200):
        raise RuntimeError("provider down")

    monkeypatch.setattr(orchestrator, "_complete", failing)
    run = orchestrator.create_run("demo", "Implement a health endpoint")
    with pytest.raises(Exception) as error:
        asyncio.run(orchestrator.advance_run(run["id"]))
    assert "blocked" in str(error.value).lower() or getattr(error.value, "status_code", 0) == 502
    blocked = orchestrator.get_run(run["id"])
    assert blocked["status"] == "blocked"
    assert blocked["steps"][0]["status"] == "failed"

    monkeypatch.setattr(orchestrator, "_complete", fake_complete)
    recovered = asyncio.run(orchestrator.advance_run(run["id"]))
    assert recovered["steps"][0]["status"] == "completed"
    assert recovered["status"] == "queued"


def test_thermal_pause_blocks_advance_until_cooled(project, monkeypatch):
    monkeypatch.setenv("DEVICE_THERMAL_GUARD", "1")
    monkeypatch.setattr(orchestrator.device, "admission", lambda: {
        "allowed": False, "reason": "device is hot", "retry_after": 12,
    })
    monkeypatch.setattr(orchestrator.device, "touch_keep_awake", lambda *args, **kwargs: None)
    run = orchestrator.create_run("demo", "Implement a health endpoint")
    with pytest.raises(Exception) as error:
        asyncio.run(orchestrator.advance_run(run["id"]))
    assert getattr(error.value, "status_code", 0) == 409
    assert "hot" in str(getattr(error.value, "detail", error.value))
    assert getattr(error.value, "headers", {}).get("Retry-After") == "12"
    assert orchestrator.get_run(run["id"])["status"] == "queued"


def test_cancel_prevents_further_advance(project, monkeypatch):
    monkeypatch.setattr(orchestrator, "_complete", fake_complete)
    run = orchestrator.create_run("demo", "Implement a health endpoint")
    cancelled = orchestrator.cancel_run(run["id"])
    assert cancelled["status"] == "cancelled"
    assert all(step["status"] == "cancelled" for step in cancelled["steps"])
    with pytest.raises(Exception) as error:
        asyncio.run(orchestrator.advance_run(run["id"]))
    assert getattr(error.value, "status_code", 0) == 409


def source_snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".agent" not in path.parts
    }


def test_runs_never_touch_project_files(project, monkeypatch):
    before = source_snapshot(project)
    monkeypatch.setattr(orchestrator, "_complete", fake_complete)
    run = orchestrator.create_run("demo", "Rewrite the entire application")
    asyncio.run(orchestrator.advance_run(run["id"]))
    assert source_snapshot(project) == before


def test_agent_endpoints_require_auth_and_are_bounded(project, monkeypatch):
    monkeypatch.setattr(orchestrator, "_complete", fake_complete)
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.get("/api/agents/roles").status_code == 403
    roles = client.get("/api/agents/roles", headers=headers)
    assert roles.status_code == 200
    assert {role["name"] for role in roles.json()["roles"]} >= {"architect", "security"}
    created = client.post("/api/agents/runs",
                          json={"project": "demo", "goal": "Add a health endpoint"},
                          headers=headers)
    assert created.status_code == 200
    run_id = created.json()["id"]
    advanced = client.post(f"/api/agents/runs/{run_id}/advance", headers=headers)
    assert advanced.status_code == 200
    assert advanced.json()["steps"][0]["status"] == "completed"
    listed = client.get("/api/agents/runs?project=demo", headers=headers)
    assert listed.status_code == 200
    detail = client.get(f"/api/agents/runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    assert client.get("/api/agents/runs?project=bad/../name", headers=headers).status_code == 400
    assert client.get("/api/agents/runs/" + "f" * 32, headers=headers).status_code == 404
    cancelled = client.post(f"/api/agents/runs/{run_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
