"""Regression tests for incremental, bounded, and million-line indexing."""
from services.api import engine, code_index

def test_index_refresh_delete_and_change(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    project = engine.workspace("demo")
    one = project / "main.py"
    one.write_text("def calculate_invoice():\n    return 42\n")
    assert code_index.index_project("demo")["updated"] == 1
    assert code_index.search_project("demo", "calculate_invoice")[0]["path"] == "main.py"
    assert code_index.index_project("demo")["unchanged"] == 1
    one.write_text("def calculate_receipt():\n    return 42\n")
    assert code_index.index_project("demo")["updated"] == 1
    assert code_index.search_project("demo", "calculate_invoice") == []
    one.unlink()
    assert code_index.index_project("demo")["removed"] == 1
    assert code_index.search_project("demo", "calculate_receipt") == []

def test_partial_scan_does_not_delete_or_follow_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    for n in range(3):
        (root / f"f{n}.py").write_text(f"uniqueanswer{n}\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.py").write_text("ignorethisvalue")
    assert code_index.index_project("demo", 10)["indexed_files"] == 3
    partial = code_index.index_project("demo", 1)
    assert partial["truncated"]
    assert partial["indexed_files"] == 3
    assert code_index.search_project("demo", "uniqueanswer2")
    assert not code_index.search_project("demo", "ignorethisvalue")

def test_oversized_file_becomes_unsearchable(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    p = root / "file.py"
    p.write_text("somethingsearchable")
    code_index.index_project("demo")
    p.write_text("somethingsearchable\n" + "a" * (code_index.MAX_FILE_BYTES + 1))
    assert code_index.index_project("demo")["skipped"] == 1
    assert not code_index.search_project("demo", "somethingsearchable")

def test_index_line_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path)
    root = engine.workspace("demo")
    (root / "m.py").write_text("line1\nline2\nline3\n")
    report = code_index.index_project("demo")
    assert report["indexed_lines"] == 3
    assert report["indexed_files"] == 1
    assert code_index.search_project("demo", "line3")
