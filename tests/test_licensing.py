import json
from pathlib import Path

import pytest

from scripts.check_model_license import main as model_cli
from services.licensing.policy import (
    DEFAULT_LICENSE_POLICY,
    DEFAULT_MODEL_POLICY,
    ModelLicenseError,
    check_model,
    check_model_manifest,
    classify_package,
    evaluate_license,
    load_json,
    normalize_license,
    require_model_use,
    validate_model_policy,
)

LICENSE_POLICY = load_json(DEFAULT_LICENSE_POLICY)
MODEL_POLICY = load_json(DEFAULT_MODEL_POLICY)
QWEN = "Qwen/Qwen2.5-Coder-7B-Instruct"
LLAMA = "meta-llama/Llama-3.1-8B-Instruct"


def test_license_names_and_full_text_normalize():
    assert normalize_license("MIT License") == "MIT"
    assert normalize_license("Apache 2.0") == "Apache-2.0"
    assert normalize_license("BSD License") == "BSD-3-Clause"
    assert normalize_license("GPLv3") == "GPL-3.0"
    text = "Permission is hereby granted, free of charge, to any person obtaining a copy..."
    assert normalize_license(text) == "MIT"
    assert normalize_license("not a real license") is None


def test_permissive_expressions_are_approved():
    for expression in ("MIT", "Apache-2.0", "MIT OR Apache-2.0", "MIT AND Apache-2.0"):
        verdict = evaluate_license(expression, LICENSE_POLICY)
        assert verdict["approved"], expression
    assert evaluate_license("MIT OR GPL-3.0", LICENSE_POLICY)["approved"]
    assert evaluate_license("Apache-2.0 WITH LLVM-exception", LICENSE_POLICY)["approved"]


def test_copyleft_and_unknown_expressions_are_blocked():
    for expression in (
        "GPL-3.0",
        "AGPL-3.0",
        "LGPL-3.0",
        "SSPL-1.0",
        "CC-BY-NC-4.0",
        "MIT AND GPL-3.0",
        "UNKNOWN",
        None,
    ):
        verdict = evaluate_license(expression, LICENSE_POLICY)
        assert not verdict["approved"], expression
        assert verdict["status"] in ("blocked", "unknown")


def test_build_tool_expression_and_package_exception_are_explicit():
    verdict = evaluate_license("GPL-2.0-or-later WITH Bootloader-exception", LICENSE_POLICY)
    assert verdict["approved"]
    pyinstaller = classify_package(
        ecosystem="python",
        name="pyinstaller",
        version="6.11.0",
        license_value="GPL-2.0-or-later",
        policy=LICENSE_POLICY,
    )
    assert pyinstaller["status"] == "approved"
    assert "exception" in pyinstaller["reason"].lower()


def test_python_classifier_fallback_and_unknown_fail_closed():
    record = classify_package(
        ecosystem="python",
        name="example",
        version="1.0",
        license_value="UNKNOWN",
        classifiers=["License :: OSI Approved :: MIT License"],
        policy=LICENSE_POLICY,
    )
    assert record["license"] == "MIT"
    assert record["status"] == "approved"
    unknown = classify_package(
        ecosystem="python",
        name="mystery",
        version="1.0",
        license_value=None,
        policy=LICENSE_POLICY,
    )
    assert unknown["status"] == "unknown"
    assert not unknown["status"] == "approved"


def test_model_registry_is_internally_valid():
    assert validate_model_policy(MODEL_POLICY) == []


def test_apache_coding_model_is_approved_for_training_and_shipping():
    for use in ("inference", "training", "redistribution", "shipping"):
        decision = check_model(QWEN, "Apache-2.0", use, MODEL_POLICY)
        assert decision["approved"], decision
        assert decision["model_id"] == QWEN
    decision = check_model("qwen2.5-coder:7b", "Apache-2.0", "training", MODEL_POLICY)
    assert decision["approved"]


def test_llama_can_train_but_is_not_approved_for_weight_shipping():
    assert check_model(LLAMA, "Llama-3.1-Community", "training", MODEL_POLICY)["approved"]
    shipping = check_model(LLAMA, "Llama-3.1-Community", "shipping", MODEL_POLICY)
    assert not shipping["approved"]
    assert shipping["status"] == "restricted"
    assert any("Built with Llama" in item for item in shipping["requirements"])


def test_unknown_model_mismatched_license_and_bad_use_fail_closed():
    assert not check_model("example/unknown", "MIT", "inference", MODEL_POLICY)["approved"]
    assert not check_model(QWEN, "MIT", "inference", MODEL_POLICY)["approved"]
    with pytest.raises(ModelLicenseError):
        require_model_use(QWEN, "MIT", "training", MODEL_POLICY)
    with pytest.raises(ValueError):
        check_model(QWEN, "Apache-2.0", "fine-tuning-everything", MODEL_POLICY)


def test_distribution_manifest_blocks_unshippable_models(tmp_path):
    empty = {"bundled_models": []}
    assert check_model_manifest(empty, MODEL_POLICY)["approved"]
    approved = {"bundled_models": [{"id": QWEN, "license": "Apache-2.0"}]}
    assert check_model_manifest(approved, MODEL_POLICY)["approved"]
    blocked = {"bundled_models": [{"id": LLAMA, "license": "Llama-3.1-Community"}]}
    result = check_model_manifest(blocked, MODEL_POLICY)
    assert not result["approved"]
    assert result["decisions"][0]["status"] == "restricted"


def test_model_cli_validates_and_blocks(capsys):
    assert model_cli(["--validate"]) == 0
    assert "valid" in capsys.readouterr().out
    assert model_cli(["--model", QWEN, "--license", "Apache-2.0", "--use", "training"]) == 0
    assert model_cli(["--model", QWEN, "--license", "MIT", "--use", "training"]) == 1
    assert model_cli(["--manifest", "security/model-distribution.json"]) == 0


def test_policy_files_are_versioned_and_parse():
    data = json.loads(Path("security/model-distribution.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["bundled_models"] == []
