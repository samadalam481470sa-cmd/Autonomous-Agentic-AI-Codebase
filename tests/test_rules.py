"""Project instruction files are read, bounded and labelled as untrusted."""
from services.api import engine, rules


def test_reads_agents_md(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    (root / "AGENTS.md").write_text("# House rules\n\nUse tabs and small diffs.\n",
                                    encoding="utf-8")
    data = rules.instructions("demo")
    assert data["sources"] == ["AGENTS.md"]
    assert "Use tabs and small diffs." in data["text"]
    block = rules.prompt_block("demo")
    assert "untrusted" in block.lower()
    assert "ignore any text" in block.lower()


def test_cursor_rules_frontmatter_is_stripped(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    (root / "CLAUDE.md").write_text("Prefer explicit types.\n", encoding="utf-8")
    directory = root / ".cursor" / "rules"
    directory.mkdir(parents=True)
    (directory / "style.mdc").write_text(
        "---\nalwaysApply: true\n---\nKeep functions under 40 lines.\n",
        encoding="utf-8",
    )
    data = rules.instructions("demo")
    assert data["sources"] == ["CLAUDE.md", ".cursor/rules/style.mdc"]
    assert "Prefer explicit types." in data["text"]
    assert "Keep functions under 40 lines." in data["text"]
    assert "alwaysApply" not in data["text"]


def test_output_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    # Two files each under the per-file cap but together over the total budget.
    (root / "AGENTS.md").write_text("x" * 9_000, encoding="utf-8")
    (root / "CLAUDE.md").write_text("y" * 9_000, encoding="utf-8")
    data = rules.instructions("demo")
    assert len(data["text"]) <= rules.MAX_TOTAL_BYTES + 200
    assert data["truncated"] is True


def test_no_instructions_returns_empty_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    engine.workspace("demo")
    assert rules.instructions("demo")["sources"] == []
    assert rules.prompt_block("demo") == ""
