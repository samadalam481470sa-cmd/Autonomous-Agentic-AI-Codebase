"""Polyglot scaffolding, toolchain execution and the autonomous solve loop."""
import pytest
from fastapi.testclient import TestClient

from services.api import engine, polyglot, security, toolchains, worker
from services.api.main import app

TOKEN = "polyglot-test-token-1234567890"
HEADERS = {"Authorization": "Bearer " + TOKEN}
APPROVED = {**HEADERS, "X-Confirm-Execution": "approve", "X-Confirm-Change": "approve"}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("AGENT_HOST_TOOLCHAIN", "1")
    monkeypatch.setenv("AGENT_AUTONOMY", "1")
    monkeypatch.setenv("POLYGLOT_TOOLCHAINS_PATH", str(tmp_path / "toolchains.json"))
    monkeypatch.setenv("WORKER_DB_PATH", str(tmp_path / "worker.sqlite3"))
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    toolchains.reset_cache()
    security.reset()
    yield
    security.reset()


def test_language_report_requires_token(isolated):
    client = TestClient(app)
    assert client.get("/api/polyglot/languages").status_code == 403
    report = client.get("/api/polyglot/languages", headers=HEADERS).json()
    assert report["language_count"] >= 55
    assert report["host_toolchain_enabled"] is True
    python = next(item for item in report["languages"] if item["language"] == "python")
    assert python["installed"] is True


def test_scaffold_python_and_verify(isolated):
    client = TestClient(app)
    response = client.post("/api/polyglot/scaffold",
                           headers={**HEADERS, "X-Confirm-Change": "approve"},
                           json={"project": "demo", "language": "python"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["files"][0]["path"] == "main.py"
    assert data["verified"] is True, data
    source = engine.ROOT / "demo" / "main.py"
    assert source.is_file() and "print" in source.read_text(encoding="utf-8")


def test_scaffold_needs_approval_without_autonomy(isolated, monkeypatch):
    monkeypatch.delenv("AGENT_AUTONOMY", raising=False)
    client = TestClient(app)
    denied = client.post("/api/polyglot/scaffold", headers=HEADERS,
                         json={"project": "demo", "language": "python", "verify": False})
    assert denied.status_code == 428
    allowed = client.post("/api/polyglot/scaffold",
                          headers={**HEADERS, "X-Confirm-Change": "approve"},
                          json={"project": "demo", "language": "python", "verify": False})
    assert allowed.status_code == 200


def test_unknown_language_is_a_client_error(isolated):
    client = TestClient(app)
    response = client.post("/api/polyglot/scaffold", headers=APPROVED,
                           json={"project": "demo", "language": "not-real"})
    assert response.status_code == 400


def test_detect_and_execute_project_language(isolated):
    client = TestClient(app)
    root = engine.workspace("demo")
    (root / "main.py").write_text('print("detected and run")\n', encoding="utf-8")
    (root / "lib.rs").write_text("fn main() {}\n", encoding="utf-8")
    detected = client.post("/api/polyglot/detect", headers=HEADERS,
                           json={"project": "demo"}).json()
    languages = {item["language"]: item for item in detected["languages"]}
    assert languages["python"]["files"] == 1
    assert languages["rust"]["files"] == 1
    assert all("install_hint" in item for item in detected["languages"])

    run = client.post("/api/polyglot/run", headers=APPROVED,
                      json={"project": "demo", "language": "python",
                            "action": "run", "path": "main.py"})
    assert run.status_code == 200, run.text
    assert "detected and run" in run.json()["steps"][-1]["stdout"]


def test_host_execution_is_opt_in(isolated, monkeypatch):
    monkeypatch.delenv("AGENT_HOST_TOOLCHAIN", raising=False)
    client = TestClient(app)
    assert client.post("/api/polyglot/run", headers=APPROVED,
                       json={"project": "demo", "language": "python",
                             "action": "check", "path": "main.py"}).status_code == 503
    assert client.post("/api/polyglot/solve", headers=APPROVED,
                       json={"project": "demo", "instruction": "write python code",
                             "language": "python"}).status_code == 503


def test_missing_toolchain_is_reported(isolated):
    toolchains.register_custom({
        "language": "ghostlang", "extensions": [".ghost"],
        "probes": [["definitely-not-installed-ghost", "--version"]],
        "run": ["{exe}", "{file}"],
    })
    client = TestClient(app)
    response = client.post("/api/polyglot/solve", headers=APPROVED,
                           json={"project": "demo", "instruction": "write ghost code",
                                 "language": "ghostlang", "path": "main.ghost"})
    assert response.status_code == 409
    assert "toolchain is not installed" in response.json()["detail"]


def test_custom_language_registration_endpoint(isolated):
    client = TestClient(app)
    response = client.post("/api/polyglot/register", headers=HEADERS, json={
        "language": "tinylang", "extensions": [".tiny"],
        "probes": [["python3", "--version"]],
        "run": ["{exe}", "{file}"], "install": "Install tinylang",
    })
    assert response.status_code == 200, response.text
    assert response.json()["registered"]["installed"] is True
    report = client.get("/api/polyglot/languages", headers=HEADERS).json()
    assert "tinylang" in {item["language"] for item in report["languages"]}


def test_solve_requires_model_configuration(isolated, monkeypatch):
    monkeypatch.delenv("LOCAL_MODEL_ONLY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = TestClient(app)
    response = client.post("/api/polyglot/solve", headers=APPROVED,
                           json={"project": "demo", "instruction": "write a greeting",
                                 "language": "python", "path": "greet.py"})
    assert response.status_code == 503


def test_solve_generates_verifies_and_applies(isolated, monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_ONLY", "1")
    monkeypatch.setenv("LOCAL_MODEL_BASE_URL", "http://127.0.0.1:9931/v1")

    async def fake_chat(base, model, key, messages, max_tokens=4096):
        assert "python" in messages[1]["content"]
        return 'print("autonomous polyglot output")\n'

    monkeypatch.setattr(polyglot, "_chat", fake_chat)
    client = TestClient(app)
    response = client.post("/api/polyglot/solve", headers=APPROVED, json={
        "project": "demo", "instruction": "write a python greeting to stdout",
        "language": "python", "path": "agent_generated.py",
        "attempts": 1, "apply": True,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["trial_passed"] is True, data
    assert data["applied"] is True, data
    assert data["live_verification"]["passed"] is True
    content = (engine.ROOT / "demo" / "agent_generated.py").read_text(encoding="utf-8")
    assert "autonomous polyglot output" in content


def test_solve_retries_after_a_failed_compile(isolated, monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_ONLY", "1")
    monkeypatch.setenv("LOCAL_MODEL_BASE_URL", "http://127.0.0.1:9931/v1")
    calls = {"count": 0}

    async def flaky_chat(base, model, key, messages, max_tokens=4096):
        calls["count"] += 1
        if calls["count"] == 1:
            return "print('unterminated\n"
        return 'print("fixed on retry")\n'

    monkeypatch.setattr(polyglot, "_chat", flaky_chat)
    client = TestClient(app)
    response = client.post("/api/polyglot/solve", headers=APPROVED, json={
        "project": "demo", "instruction": "write a python program that prints",
        "language": "python", "path": "retry.py", "attempts": 2, "apply": False,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["trial_passed"] is True
    assert data["attempts"] == 2
    assert data["applied"] is False
    assert not (engine.ROOT / "demo" / "retry.py").exists()


def test_solve_can_be_queued_durably(isolated):
    client = TestClient(app)
    response = client.post("/api/polyglot/solve", headers=APPROVED, json={
        "project": "demo", "instruction": "queue a python task",
        "language": "python", "path": "queued.py", "queue": True,
    })
    assert response.status_code == 200, response.text
    assert response.json()["queued"] is True
    jobs = worker.list_jobs()
    assert jobs and jobs[0]["kind"] == "polyglot.solve"
    assert jobs[0]["status"] == "queued"
    assert jobs[0]["payload"]["project"] == "demo"
