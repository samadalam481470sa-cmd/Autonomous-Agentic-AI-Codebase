"""Durable queue, scheduling decisions and worker control API."""
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from services.api import engine, security, worker
from services.api.main import app

TOKEN = "worker-test-token-1234567890"
HEADERS = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKER_DB_PATH", str(tmp_path / "worker.sqlite3"))
    monkeypatch.setenv("AGENT_WORKER_ENABLED", "0")
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("AGENT_AUTONOMY", raising=False)
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    worker.runtime.stop()
    worker.HANDLERS.clear()
    worker.GPU_CACHE["value"] = None
    security.reset()
    yield
    worker.HANDLERS.clear()
    worker.runtime.stop()
    security.reset()


def force_runnable(monkeypatch):
    monkeypatch.setattr(worker, "decision_for_now", lambda path=None: (
        True, "running", {"state": {}, "gpu": {}, "power": {}}))


def test_enqueue_claim_and_complete(isolated):
    job = worker.enqueue("noop", {"a": 1})
    claimed = worker.claim(worker_id="test-worker")
    assert claimed["id"] == job["job_id"]
    assert claimed["payload"] == {"a": 1}
    assert claimed["attempts"] == 1
    assert worker.claim() is None
    assert worker.complete(claimed["id"], {"ok": True}) is True
    stored = worker.list_jobs()[0]
    assert stored["status"] == "completed"
    assert stored["result"] == {"ok": True}


def test_failures_retry_then_fail(isolated):
    job = worker.enqueue("noop", {}, max_attempts=2)
    first = worker.claim()
    retry = worker.fail(first["id"], "first boom")
    assert retry["status"] == "queued"
    assert worker.claim() is None  # retry delay is in the future
    with closing(worker.connect()) as con, con:
        con.execute("UPDATE jobs SET next_run_at=0 WHERE id=?", (job["job_id"],))
    second = worker.claim()
    assert second["id"] == job["job_id"] and second["attempts"] == 2
    failed = worker.fail(second["id"], "second boom")
    assert failed["status"] == "failed"
    assert worker.list_jobs()[0]["error"] == "second boom"


def test_payload_limits_and_kind_validation(isolated):
    with pytest.raises(ValueError):
        worker.enqueue("Bad Kind", {})
    with pytest.raises(ValueError):
        worker.enqueue("noop", {"blob": "x" * 70_000})
    with pytest.raises(ValueError):
        worker.enqueue("noop", ["not", "an", "object"])


def test_cancel_and_recover_interrupted_jobs(isolated):
    job = worker.enqueue("noop", {})
    claimed = worker.claim()
    assert worker.cancel(claimed["id"]) is True
    assert worker.list_jobs()[0]["status"] == "cancelled"
    assert worker.cancel(claimed["id"]) is False

    stuck = worker.enqueue("noop", {})
    worker.claim()
    with closing(worker.connect()) as con, con:
        con.execute("UPDATE jobs SET started_at=? WHERE id=?", (worker.now() - 4000, stuck["job_id"]))
    recovered = worker.recover(stale_seconds=60)
    assert recovered["requeued"] == 1
    statuses = {item["id"]: item["status"] for item in worker.list_jobs()}
    assert statuses[stuck["job_id"]] == "queued"


def test_decide_policies():
    base = dict(enabled="1", paused="0", policy="always", active_hours="0-24",
                hour=12, on_ac=True, gpu_temperature_c=40, max_gpu_temp_c=85)
    assert worker.decide(**base) == (True, "running")
    assert worker.decide(**{**base, "enabled": "0"}) == (False, "disabled")
    assert worker.decide(**{**base, "paused": "1"}) == (False, "paused")
    assert worker.decide(**{**base, "policy": "off"}) == (False, "policy_off")
    assert worker.decide(**{**base, "policy": "ac_only", "on_ac": False}) == (False, "on_battery")
    assert worker.decide(**{**base, "policy": "ac_only", "on_ac": True}) == (True, "running")
    assert worker.decide(**{**base, "active_hours": "9-17", "hour": 20}) == (False, "outside_active_hours")
    assert worker.decide(**{**base, "gpu_temperature_c": 91}) == (False, "gpu_thermal_guard")
    assert worker.decide(**{**base, "active_hours": "not-hours"}) == (False, "invalid_active_hours")


def test_active_hours_wrap_midnight():
    assert worker.in_hours(23, "22-7") is True
    assert worker.in_hours(6, "22-7") is True
    assert worker.in_hours(12, "22-7") is False
    assert worker.in_hours(0, "0-24") is True
    assert worker.in_hours(23, "0-24") is True
    for invalid in ("", "abc", "25-3", "9-30"):
        with pytest.raises(ValueError):
            worker.parse_hours(invalid)


def test_tick_runs_registered_handler(isolated, monkeypatch):
    force_runnable(monkeypatch)
    worker.register_handler("test.echo", lambda payload: {"echo": payload})
    job = worker.enqueue("test.echo", {"x": 1})
    result = worker.tick()
    assert result["ran"] is True and result["status"] == "completed"
    assert worker.list_jobs()[0]["result"] == {"echo": {"x": 1}}
    assert job["job_id"] == result["job_id"]


def test_tick_records_unknown_handler_failure(isolated, monkeypatch):
    force_runnable(monkeypatch)
    worker.enqueue("missing.kind", {}, max_attempts=1)
    result = worker.tick()
    assert result["status"] == "failed"
    assert "No handler" in result["error"]


def test_tick_does_not_claim_when_paused(isolated, monkeypatch):
    monkeypatch.setattr(worker, "decision_for_now", lambda path=None: (False, "paused", {}))
    worker.enqueue("noop", {})
    assert worker.tick()["reason"] == "paused"
    assert worker.stats()["queued"] == 1


def test_runtime_thread_processes_a_job(isolated, monkeypatch):
    force_runnable(monkeypatch)
    worker.register_handler("test.thread", lambda payload: {"done": True})
    worker.state_set("enabled", "1")
    worker.state_set("paused", "0")
    worker.enqueue("test.thread", {})
    worker.runtime.start(poll_seconds=0.2)
    try:
        for _ in range(60):
            if worker.list_jobs()[0]["status"] == "completed":
                break
            time.sleep(0.05)
    finally:
        worker.runtime.stop()
    assert worker.list_jobs()[0]["status"] == "completed"
    assert worker.runtime.status()["thread_running"] is False


def test_worker_control_api(isolated, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/worker/status").status_code == 403
    body = client.get("/api/worker/status", headers=HEADERS).json()
    assert body["queue"]["queued"] == 0
    assert "always" in body["policies"]
    assert body["usage"]

    assert client.post("/api/worker/pause", headers=HEADERS).json()["paused"] is True
    assert worker.load_state()["paused"] == "1"
    assert client.post("/api/worker/resume", headers=HEADERS).json()["paused"] is False
    assert client.post("/api/worker/stop", headers=HEADERS).json()["enabled"] is False
    assert worker.load_state()["enabled"] == "0"
    monkeypatch.setattr(worker.runtime, "start", lambda *args, **kwargs: True)
    assert client.post("/api/worker/start", headers=HEADERS).json()["enabled"] is True

    assert client.post("/api/worker/policy", headers=HEADERS,
                       json={"policy": "sometimes"}).status_code == 400
    assert client.post("/api/worker/policy", headers=HEADERS,
                       json={"active_hours": "99-300"}).status_code == 400
    saved = client.post("/api/worker/policy", headers=HEADERS,
                        json={"policy": "ac_only", "active_hours": "22-7",
                              "max_gpu_temp_c": 80})
    assert saved.status_code == 200
    assert worker.load_state()["policy"] == "ac_only"


def test_jobs_api_and_manual_tick(isolated, monkeypatch):
    client = TestClient(app)
    created = client.post("/api/worker/jobs", headers=HEADERS,
                          json={"kind": "noop", "payload": {"x": 1}})
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    listed = client.get("/api/worker/jobs", headers=HEADERS).json()
    assert listed["queue"]["queued"] == 1

    force_runnable(monkeypatch)
    assert client.post("/api/worker/tick", headers=HEADERS).status_code == 428
    ticked = client.post("/api/worker/tick",
                         headers={**HEADERS, "X-Confirm-Execution": "approve"})
    assert ticked.status_code == 200
    assert ticked.json()["status"] == "completed"
    stored = client.get("/api/worker/jobs", headers=HEADERS).json()["jobs"][0]
    assert stored["id"] == job_id
    assert stored["result"]["payload"] == {"x": 1}

    cancelled = client.post("/api/worker/jobs/" + job_id + "/cancel", headers=HEADERS)
    assert cancelled.status_code == 409
