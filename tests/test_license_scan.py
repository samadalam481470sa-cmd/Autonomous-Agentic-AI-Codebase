import json
from pathlib import Path

import pytest

from scripts.license_scan import (
    ScanError,
    dedupe,
    main,
    scan_declared_python,
    scan_models,
    scan_node,
    scan_vendored,
)
from services.licensing.policy import load_json

ROOT = Path(__file__).resolve().parents[1]
POLICY = load_json(ROOT / "security" / "license-policy.json")


def write_package(directory: Path, name: str, version: str, license_value: str) -> None:
    path = directory / "node_modules" / name / "package.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"name": name, "version": version, "license": license_value}),
        encoding="utf-8",
    )


def test_node_scan_blocks_denied_missing_and_unknown(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "fixture-app",
                "version": "1.0.0",
                "license": "MIT",
                "dependencies": {"good": "1.0.0", "bad": "1.0.0", "missing": "1.0.0"},
            }
        ),
        encoding="utf-8",
    )
    write_package(tmp_path, "good", "1.0.0", "MIT")
    write_package(tmp_path, "bad", "1.0.0", "GPL-3.0")
    records = scan_node(tmp_path, POLICY)
    by_name = {record["name"]: record for record in records}
    assert by_name["fixture-app"]["status"] == "approved"
    assert by_name["good"]["status"] == "approved"
    assert by_name["bad"]["status"] == "blocked"
    assert by_name["missing"]["status"] == "blocked"
    assert any("not installed" in record["reason"] for record in records if record["name"] == "missing")


def test_node_scan_requires_an_install_when_dependencies_exist(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "fixture", "version": "1.0.0", "dependencies": {"x": "1"}}),
        encoding="utf-8",
    )
    with pytest.raises(ScanError, match="No node_modules"):
        scan_node(tmp_path, POLICY)


def test_node_scan_handles_dependency_free_package(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "@autonomous-agentic-ai/ui",
                "version": "0.1.0",
                "license": "MIT",
            }
        ),
        encoding="utf-8",
    )
    records = scan_node(tmp_path, POLICY)
    assert len(records) == 1
    assert records[0]["status"] == "approved"


def test_declared_python_and_vendored_repository_are_approved():
    declared = scan_declared_python(ROOT, POLICY)
    assert declared
    assert all(record["status"] in ("approved", "conditional") for record in declared)
    vendored = scan_vendored(ROOT, POLICY)
    assert any(record["name"] == "third_party/monaco-editor" and record["status"] == "approved" for record in vendored)
    assert any(record["name"] == "first-party-source" and record["status"] == "approved" for record in vendored)


def test_model_registry_and_empty_distribution_manifest_are_approved():
    records, manifest = scan_models(
        ROOT,
        ROOT / "security" / "model-policy.json",
        ROOT / "security" / "model-distribution.json",
    )
    assert manifest and manifest["approved"]
    assert any(record["ecosystem"] == "model" and record["status"] == "approved" for record in records)
    assert any(record["status"] == "conditional" for record in records)


def test_dedupe_is_deterministic():
    records = [
        {"ecosystem": "npm", "name": "x", "version": "1", "status": "approved"},
        {"ecosystem": "npm", "name": "X", "version": "1", "status": "blocked"},
    ]
    assert len(dedupe(records)) == 1


def test_cli_passes_real_repository_policy(capsys):
    assert main(["--requirements", "--vendored", "--models", "--quiet"]) == 0
    captured = capsys.readouterr()
    assert "PASS" in captured.out
