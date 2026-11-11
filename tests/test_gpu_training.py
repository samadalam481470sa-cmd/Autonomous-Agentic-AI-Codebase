"""Consent-gated GPU LoRA orchestration: export, validation, API and rollback."""
import pytest
from fastapi.testclient import TestClient

from services.api import engine, gpu_training, lifelong, security
from services.api.main import app

TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def gpu_project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("LEARNING_STATE_PATH", str(tmp_path / "learning-state.sqlite3"))
    monkeypatch.setenv("AETHERION_LEARN_CAPTURE", "1")
    monkeypatch.setenv("AETHERION_CONTINUOUS", "0")
    monkeypatch.setenv("AETHERION_LORA_TRAIN", "1")
    monkeypatch.setenv("AETHERION_LORA_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("AETHERION_LORA_MODEL_ID", "Qwen/Qwen2.5-Coder-7B-Instruct")
    monkeypatch.setenv("AETHERION_LORA_MODEL_LICENSE", "Apache-2.0")
    (tmp_path / "model").mkdir()
    security.reset()
    root = engine.workspace("demo")
    (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
    for index in range(12):
        ident = lifelong.capture(
            "demo", "ask", f"Question {index}", f"Accepted answer {index}",
            [{"path": "app.py", "line": 1}],
        )
        assert lifelong.rate("demo", ident, "up")["rated"]
    return root


def test_export_is_idempotent_and_only_uses_accepted_answers(gpu_project):
    first = lifelong.export_feedback("demo")
    assert first == {"available": 12, "inserted": 12, "required": 12}
    second = lifelong.export_feedback("demo")
    assert second["available"] == 12
    assert second["inserted"] == 0

    rejected = lifelong.capture("demo", "ask", "Rejected prompt", "Rejected answer")
    lifelong.rate("demo", rejected, "down")
    third = lifelong.export_feedback("demo")
    assert third["available"] == 12
    assert third["inserted"] == 0


def test_gpu_status_reports_prerequisites_without_a_gpu(gpu_project, monkeypatch):
    monkeypatch.setattr(gpu_training.power, "gpu_status", lambda: {"detected": False})
    status = gpu_training.status("demo")
    assert status["enabled"] is True
    assert status["approved_examples"] == 12
    assert status["required_examples"] == 12
    assert set(status["dependencies"]) == {"torch", "transformers", "peft", "safetensors"}
    assert status["config"]["model_id"] == "Qwen/Qwen2.5-Coder-7B-Instruct"
    assert status["can_train"] is False  # this CI machine has no usable GPU
    assert any("GPU" in reason or "graphics" in reason for reason in status["reasons"])


def test_start_requires_consent_and_a_reviewed_license(gpu_project, monkeypatch):
    with pytest.raises(PermissionError):
        gpu_training.start("demo", consent=False)

    monkeypatch.setenv("AETHERION_LORA_TRAIN", "0")
    with pytest.raises(RuntimeError, match="disabled"):
        gpu_training.start("demo", consent=True)

    monkeypatch.setenv("AETHERION_LORA_TRAIN", "1")
    monkeypatch.setenv("AETHERION_LORA_MODEL_LICENSE", "MIT")
    with pytest.raises(ValueError, match="license gate"):
        gpu_training.start("demo", consent=True)

    monkeypatch.setenv("AETHERION_LORA_MODEL_LICENSE", "Apache-2.0")
    monkeypatch.setattr(
        gpu_training.power, "gpu_status", lambda: {"detected": False}
    )
    with pytest.raises(RuntimeError, match="No compatible local"):
        gpu_training.start("demo", consent=True)


def test_gpu_api_consent_and_status(gpu_project, monkeypatch):
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    response = client.get("/api/learning/demo/gpu-training", headers=headers)
    assert response.status_code == 200
    assert response.json()["approved_examples"] == 12

    denied = client.post(
        "/api/learning/demo/gpu-training", json={"consent": False}, headers=headers
    )
    assert denied.status_code == 428

    monkeypatch.setenv("AETHERION_LORA_TRAIN", "0")
    disabled = client.post(
        "/api/learning/demo/gpu-training", json={"consent": True}, headers=headers
    )
    assert disabled.status_code == 409


def test_rollback_uses_the_trainer_manifest(gpu_project):
    from scripts.local_lora_training import activate

    versions = gpu_project / ".agent" / "models" / "versions"
    for version in ("one", "two"):
        directory = versions / version
        directory.mkdir(parents=True)
        (directory / "adapter_config.json").write_text("{}", encoding="utf-8")
    activate(gpu_project, "one", 1.2, 1.0, "/local/model")
    activate(gpu_project, "two", 1.0, 0.8, "/local/model")

    result = gpu_training.rollback("demo")
    assert result["rolled_back"] is True
    assert result["adapter"]["active"] == "one"
    with pytest.raises(ValueError):
        gpu_training.rollback("demo")
