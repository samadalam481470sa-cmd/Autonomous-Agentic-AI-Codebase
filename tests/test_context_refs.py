"""@-mentions are parsed, contained to the project and budgeted."""
from services.api import context_refs, engine


def test_parse_deduplicates_and_trims_punctuation():
    assert context_refs.parse("see @file:src/app.py and @folder:tests.") == [
        "file:src/app.py", "folder:tests"
    ]
    assert context_refs.parse("@file:src/app.py @file:src/app.py") == ["file:src/app.py"]
    assert context_refs.parse("no mentions here") == []
    assert context_refs.parse(None) == []


def test_resolves_a_file_and_a_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    data = context_refs.resolve("demo", "look at @file:src/app.py and @folder:src")
    assert "print('hi')" in data["text"]
    kinds = [item["kind"] for item in data["resolved"]]
    assert kinds == ["file", "folder"]
    assert data["resolved"][0]["target"] == "src/app.py"


def test_rejects_escape_and_internal_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    (root / ".agent").mkdir()
    (root / ".agent" / "plan.json").write_text("{}", encoding="utf-8")
    data = context_refs.resolve("demo", "@file:../secret.txt @file:.agent/plan.json")
    assert data["text"] == ""
    assert all("error" in item for item in data["resolved"])


def test_budget_truncates_attached_content(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    (root / "big.txt").write_text("y" * 20_000, encoding="utf-8")
    data = context_refs.resolve("demo", "@file:big.txt", max_chars=1000)
    assert data["chars"] <= 1000
    assert data["resolved"][0]["truncated"] is True


def test_rules_mention_attaches_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    (root / "AGENTS.md").write_text("Use pytest.\n", encoding="utf-8")
    data = context_refs.resolve("demo", "@rules")
    assert "Use pytest." in data["text"]
    assert data["resolved"][0]["kind"] == "rules"


def test_unknown_file_is_reported_not_leaked(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    engine.workspace("demo")
    data = context_refs.resolve("demo", "@file:missing.py")
    assert data["resolved"][0]["error"] == "file does not exist"
    assert data["text"] == ""
