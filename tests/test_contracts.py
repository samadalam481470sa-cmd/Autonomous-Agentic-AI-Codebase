"""Contracts are the single source of truth across four languages."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "packages" / "contracts"


def load_python():
    spec = importlib.util.spec_from_file_location(
        "generated_contracts", CONTRACTS / "python" / "contracts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_has_the_required_contracts():
    data = json.loads((CONTRACTS / "schemas.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    for name in ("Run", "RunEvent", "ToolCall", "ModelCall", "Approval",
                 "Artifact", "Memory", "Connector", "EvalResult"):
        assert name in data["$defs"], name
        assert data["$defs"][name]["required"], name
    event = data["$defs"]["RunEvent"]["required"]
    assert event == ["schema_version", "run_id", "sequence", "type", "actor",
                     "created_at", "payload"]


def test_generated_bindings_are_current():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_contracts.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_python_bindings_expose_required_and_optional_fields():
    contracts = load_python()
    assert contracts.SCHEMA_VERSION == 1
    assert "id" in contracts.Run.__required_keys__
    assert "worktree_path" in contracts.Run.__optional_keys__
    assert "payload" in contracts.RunEvent.__required_keys__
    assert "decided_by" in contracts.Approval.__optional_keys__


def test_all_four_languages_are_generated_with_the_envelope():
    files = {
        "typescript/index.ts": "export interface RunEvent",
        "python/contracts.py": "class RunEvent(TypedDict):",
        "rust/contracts.rs": "pub struct RunEvent",
        "go/contracts.go": "type RunEvent struct",
    }
    for relative, marker in files.items():
        text = (CONTRACTS / relative).read_text(encoding="utf-8")
        assert marker in text, relative
        assert "run_id" in text and "sequence" in text and "payload" in text, relative
