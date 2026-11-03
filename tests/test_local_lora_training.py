import json
import pytest
from scripts.local_lora_training import (
    split_examples, should_promote, activate, rollback, feature_tensors, read_only_uri,
)

def test_holdout_is_deterministic_and_disjoint():
    data=[(str(i), f"prompt {i}", f"answer {i}") for i in range(30)]
    a,b=split_examples(data)
    assert len(a)==24 and len(b)==6
    assert {v[0] for v in a}.isdisjoint({v[0] for v in b})
    assert split_examples(list(reversed(data)))==(a,b)
    with pytest.raises(ValueError):
        split_examples(data[:3])

def test_regression_gate_rejects_nan_and_worse():
    assert should_promote(1.0,0.9)
    assert not should_promote(1.0,1.1)
    assert not should_promote(1.0,float("nan"))
    assert not should_promote(0.0,0.0)

def test_adapter_activation_and_rollback(tmp_path):
    versions=tmp_path/".agent"/"models"/"versions"
    for version in ("one","two"):
        directory=versions/version
        directory.mkdir(parents=True)
        (directory/"adapter_config.json").write_text("{}")
    first=activate(tmp_path,"one",1.2,1.0,"/local/model")
    assert first["previous"] is None
    second=activate(tmp_path,"two",1.0,0.8,"/local/model")
    assert second["previous"]=="one"
    rolled=rollback(tmp_path)
    assert rolled["active"]=="one"
    with pytest.raises(ValueError):
        rollback(tmp_path)


def test_training_requires_a_reviewed_model_license(tmp_path):
    from services.licensing.policy import ModelLicenseError
    from scripts.local_lora_training import train

    with pytest.raises(ValueError, match="model-id"):
        train(tmp_path, "/nonexistent", 1, 12, 0.01, ["q_proj"], 256)
    with pytest.raises(ModelLicenseError):
        train(tmp_path, "/nonexistent", 1, 12, 0.01, ["q_proj"], 256,
              model_id="unknown/model", model_license="MIT")
    with pytest.raises(ModelLicenseError):
        train(tmp_path, "/nonexistent", 1, 12, 0.01, ["q_proj"], 256,
              model_id="Qwen/Qwen2.5-Coder-7B-Instruct", model_license="MIT")


def test_tensors_use_the_detected_accelerator():
    class FakeTorch:
        def tensor(self, values, device=None):
            return {"values": values, "device": device}

    ids, labels = feature_tensors(FakeTorch(), [1, 2], [-100, 2], "mps")
    assert ids["device"] == "mps"
    assert labels["device"] == "mps"
    assert ids["values"] == [[1, 2]]
    assert labels["values"] == [[-100, 2]]


def test_feedback_database_uri_is_read_only_and_absolute(tmp_path):
    uri = read_only_uri(tmp_path / "feedback.sqlite3")
    assert uri.startswith("file://")
    assert uri.endswith("?mode=ro")


def test_local_accelerator_selection():
    from types import SimpleNamespace
    from scripts.local_lora_training import select_training_device
    cuda=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True), backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:False)))
    apple=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False), backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:True)))
    cpu=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False), backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:False)))
    assert select_training_device(cuda)=="cuda"
    assert select_training_device(apple)=="mps"
    with pytest.raises(RuntimeError):select_training_device(cpu)
