"""The third-party registry must stay permissively licensed and attributable."""
from scripts.check_oss_licenses import validate


def test_registry_validates():
    report = validate()
    assert report["errors"] == [], report["errors"]


def test_vendored_components_are_attributed():
    report = validate()
    assert "monaco-editor" in report["names"]
    assert "MIT" in report["allowed_spdx"]


def test_copyleft_component_is_isolated():
    from scripts.check_oss_licenses import load
    entries = {entry["name"]: entry for entry in load()["repositories"]}
    agenticseek = entries["agenticSeek"]
    assert agenticseek["bundled"] is False
    assert agenticseek["isolation"].strip()
    assert agenticseek["license"].startswith("GPL")
