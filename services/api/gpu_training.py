"""Consent-gated local GPU LoRA training for accepted interactions.

The heavy lifting remains in ``scripts/local_lora_training.py``: it enforces the
reviewed model-license registry, requires a local Hugging Face model directory,
uses a deterministic held-out split, and only activates an adapter when the
candidate's evaluation loss improves. This module adds local orchestration:

* exports accepted interactions into the trainer's approved-example database;
* refuses to run without explicit consent, a GPU, dependencies and 12 examples;
* runs the trainer as a fixed argv subprocess (never a shell);
* records a local status receipt and exposes the existing rollback path.

Nothing is uploaded and no adapter is loaded into llama.cpp automatically.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import engine, lifelong, power

REPO_ROOT = Path(__file__).resolve().parents[2]
TRAINER = REPO_ROOT / "scripts" / "local_lora_training.py"
REQUIRED_EXAMPLES = 12
_RUNNING: set[str] = set()
_LOCK = threading.Lock()


def _models_dir(project: str) -> Path:
    path = engine.workspace(project) / ".agent" / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _status_file(project: str) -> Path:
    return _models_dir(project) / "training-status.json"


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write_status(project: str, payload: dict) -> None:
    path = _status_file(project)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _dependencies() -> dict[str, bool]:
    return {
        "torch": importlib.util.find_spec("torch") is not None,
        "transformers": importlib.util.find_spec("transformers") is not None,
        "peft": importlib.util.find_spec("peft") is not None,
        "safetensors": importlib.util.find_spec("safetensors") is not None,
    }


def _config() -> dict:
    return {
        "model_dir": os.getenv("AETHERION_LORA_MODEL_DIR", ""),
        "model_id": os.getenv("AETHERION_LORA_MODEL_ID", ""),
        "model_license": os.getenv("AETHERION_LORA_MODEL_LICENSE", ""),
        "steps": int(os.getenv("AETHERION_LORA_STEPS", "20")),
        "max_examples": int(os.getenv("AETHERION_LORA_MAX_EXAMPLES", "250")),
        "min_gain": float(os.getenv("AETHERION_LORA_MIN_GAIN", "0.01")),
        "max_tokens": int(os.getenv("AETHERION_LORA_MAX_TOKENS", "512")),
        "targets": os.getenv("AETHERION_LORA_TARGETS", "q_proj,v_proj"),
        "enabled": os.getenv("AETHERION_LORA_TRAIN", "0") == "1",
    }


def status(project: str) -> dict:
    approved = lifelong.summary(project)["positive"]
    gpu = power.gpu_status()
    dependencies = _dependencies()
    config = _config()
    model_dir = Path(config["model_dir"]).expanduser() if config["model_dir"] else None
    model_ready = bool(model_dir and model_dir.is_dir())
    reasons = []
    if not config["enabled"]:
        reasons.append("Set AETHERION_LORA_TRAIN=1 to allow weight training.")
    if not gpu.get("detected"):
        reasons.append("No local GPU was detected; CUDA/ROCm/MPS training is unavailable.")
    missing = [name for name, present in dependencies.items() if not present]
    if missing:
        reasons.append("Install requirements-training.txt: " + ", ".join(missing))
    if approved < REQUIRED_EXAMPLES:
        reasons.append(f"Need {REQUIRED_EXAMPLES} accepted answers; have {approved}.")
    if not model_ready:
        reasons.append("Configure AETHERION_LORA_MODEL_DIR with a local Hugging Face model.")
    if not config["model_id"] or not config["model_license"]:
        reasons.append("Configure the reviewed model id and license.")
    with _LOCK:
        running = project in _RUNNING
    active = _read_json(_models_dir(project) / "active.json")
    last = _read_json(_status_file(project))
    return {
        "enabled": config["enabled"],
        "approved_examples": approved,
        "required_examples": REQUIRED_EXAMPLES,
        "gpu": gpu,
        "dependencies": dependencies,
        "config": {**config, "model_ready": model_ready},
        "running": running,
        "can_train": not reasons,
        "reasons": reasons,
        "active_adapter": active,
        "last_run": last,
        "trainer": str(TRAINER),
        "note": (
            "Training is opt-in and runs only on this computer. The adapter is evaluated "
            "on a held-out split and is not loaded into llama.cpp automatically."
        ),
    }


def _validate(project: str, *, consent: bool, config: dict) -> dict:
    if not consent:
        raise PermissionError("Explicit consent is required for GPU weight training")
    if not config["enabled"]:
        raise RuntimeError("GPU training is disabled; set AETHERION_LORA_TRAIN=1")
    if not 1 <= int(config["steps"]) <= 100:
        raise ValueError("steps must be between 1 and 100")
    if not 12 <= int(config["max_examples"]) <= 2000:
        raise ValueError("max_examples must be between 12 and 2000")
    if not 0 <= float(config["min_gain"]) <= 0.5:
        raise ValueError("min_gain must be between 0 and 0.5")
    if not 128 <= int(config["max_tokens"]) <= 2048:
        raise ValueError("max_tokens must be between 128 and 2048")
    targets = [item.strip() for item in str(config["targets"]).split(",") if item.strip()]
    if not 1 <= len(targets) <= 8:
        raise ValueError("targets must contain 1-8 module names")
    if not config["model_dir"] or not Path(config["model_dir"]).expanduser().is_dir():
        raise ValueError("model_dir must point to a local Hugging Face model directory")
    if not config["model_id"] or not config["model_license"]:
        raise ValueError("model_id and model_license are required")
    from ..licensing.policy import ModelLicenseError, require_model_use
    try:
        require_model_use(config["model_id"], config["model_license"], "training")
    except ModelLicenseError as exc:
        raise ValueError(f"Model license gate refused training: {exc}") from exc
    if not power.gpu_status().get("detected"):
        raise RuntimeError("No compatible local CUDA/ROCm/MPS GPU was detected")
    missing = [name for name, present in _dependencies().items() if not present]
    if missing:
        raise RuntimeError(
            "Install requirements-training.txt before GPU training: " + ", ".join(missing)
        )
    exported = lifelong.export_feedback(project, REQUIRED_EXAMPLES)
    if exported["available"] < REQUIRED_EXAMPLES:
        raise ValueError(
            f"Need {REQUIRED_EXAMPLES} accepted answers; have {exported['available']}"
        )
    return {"exported": exported, "targets": targets}


def _execute(command: list[str], env: dict[str, str]) -> dict:
    result = subprocess.run(
        command, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        timeout=3600, check=False,
    )
    parsed = None
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except ValueError:
            parsed = None
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout[-8000:],
        "stderr": result.stderr[-4000:],
        "result": parsed,
    }


def _run(project: str, config: dict, targets: list[str]) -> None:
    started = int(time.time())
    _write_status(project, {"state": "running", "started_at": started, "project": project})
    command = [
        sys.executable, str(TRAINER),
        "--project", project,
        "--model-dir", str(Path(config["model_dir"]).expanduser()),
        "--model-id", config["model_id"],
        "--model-license", config["model_license"],
        "--steps", str(config["steps"]),
        "--max-examples", str(config["max_examples"]),
        "--min-gain", str(config["min_gain"]),
        "--max-tokens", str(config["max_tokens"]),
        "--target-modules", ",".join(targets),
        "--consent-to-gpu-training",
    ]
    env = dict(os.environ)
    env["WORKSPACE_ROOT"] = str(engine.ROOT)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    try:
        outcome = _execute(command, env)
        state = "completed" if outcome["exit_code"] == 0 else "failed"
        _write_status(project, {
            "state": state, "started_at": started, "finished_at": int(time.time()),
            "project": project, "result": outcome["result"],
            "exit_code": outcome["exit_code"], "stderr": outcome["stderr"],
        })
    except Exception as exc:
        _write_status(project, {
            "state": "failed", "started_at": started, "finished_at": int(time.time()),
            "project": project, "error": f"{type(exc).__name__}: {exc}"[:2000],
        })
    finally:
        with _LOCK:
            _RUNNING.discard(project)


def start(project: str, *, consent: bool, overrides: dict | None = None) -> dict:
    config = _config()
    for key, value in (overrides or {}).items():
        if value is not None and key in config:
            config[key] = value
    with _LOCK:
        if project in _RUNNING:
            raise RuntimeError("A GPU training run is already in progress for this project")
        validated = _validate(project, consent=consent, config=config)
        _RUNNING.add(project)
    thread = threading.Thread(
        target=_run, args=(project, config, validated["targets"]),
        name=f"lora-train-{project}", daemon=True,
    )
    thread.start()
    return {
        "accepted": True, "project": project, "state": "running",
        "approved_examples": validated["exported"]["available"],
        "note": "Training runs in the background. Poll the status endpoint for the result.",
    }


def rollback(project: str) -> dict:
    root = engine.workspace(project)
    try:
        from scripts.local_lora_training import rollback as trainer_rollback
        record = trainer_rollback(root)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return {"rolled_back": True, "adapter": record}
