import json
import pytest
from scripts.local_lora_training import split_examples, should_promote, activate, rollback

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


def test_local_accelerator_selection():
    from types import SimpleNamespace
    from scripts.local_lora_training import select_training_device
    cuda=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True), backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:False)))
    apple=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False), backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:True)))
    cpu=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False), backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:False)))
    assert select_training_device(cuda)=="cuda"
    assert select_training_device(apple)=="mps"
    with pytest.raises(RuntimeError):select_training_device(cpu)
