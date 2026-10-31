"""Generate and measure a 1,000,000-line local repository indexing test.

Writes temporary benchmark source files only. Does not add generated filler to Git.
Outputs reproducible JSON including a fresh index, incremental index, deletion
cleanup, and search, so scalability claims are backed by measured evidence.
"""
import json
import os
import tempfile
import time
from pathlib import Path
from scripts.generate_large_repo_benchmark import generate
from services.api import engine, code_index

def timed(call):
    start = time.perf_counter()
    result = call()
    return result, round(time.perf_counter() - start, 3)

def benchmark():
    with tempfile.TemporaryDirectory(prefix="agentic-million-lines-") as parent:
        engine.ROOT = Path(parent)
        root = engine.workspace("million_lines")
        generated, generation_seconds = timed(lambda: generate(root, 1000, 1000))
        initial, initial_seconds = timed(lambda: code_index.index_project("million_lines", 10000))
        assert initial["indexed_files"] == 1000, initial
        assert initial["indexed_lines"] == 1_000_000, initial
        match, search_seconds = timed(lambda: code_index.search_project("million_lines", "item_00500_500"))
        assert any(row["path"] == "module_00500.py" for row in match), match
        repeat, repeat_seconds = timed(lambda: code_index.index_project("million_lines", 10000))
        assert repeat["unchanged"] == 1000, repeat
        changed_file = root / "module_00500.py"
        changed_file.write_text("new_unique_symbol = 42\n", encoding="utf-8")
        changed, changed_seconds = timed(lambda: code_index.index_project("million_lines", 10000))
        assert changed["updated"] == 1, changed
        assert code_index.search_project("million_lines", "new_unique_symbol")
        assert not code_index.search_project("million_lines", "item_00500_500")
        changed_file.unlink()
        removed, remove_seconds = timed(lambda: code_index.index_project("million_lines", 10000))
        assert removed["removed"] == 1, removed
        assert not code_index.search_project("million_lines", "new_unique_symbol")
        return {
            "generated_source_lines": generated["lines"],
            "initial_indexed_lines": initial["indexed_lines"],
            "initial_indexed_files": initial["indexed_files"],
            "generation_seconds": generation_seconds,
            "initial_index_seconds": initial_seconds,
            "search_seconds": search_seconds,
            "unchanged_reindex_seconds": repeat_seconds,
            "one_changed_file_reindex_seconds": changed_seconds,
            "one_deleted_file_reindex_seconds": remove_seconds,
            "initial_index": initial,
            "incremental_index": repeat,
            "updated_index": changed,
            "deletion_index": removed,
            "caveat": "Measures lexical SQLite FTS5 indexing only, not end-to-end agent effectiveness"
        }

if __name__ == "__main__":
    result = benchmark()
    os.makedirs("reports", exist_ok=True)
    Path("reports/million_line_benchmark.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
