"""Incremental local SQLite FTS5 indexing for code repositories.

The index is deliberately bounded: it never follows symlinks, ignores generated
dependencies, indexes UTF-8 only, and does not store files larger than 1 MiB.
A scan limit cannot silently delete unseen indexed files.
"""
import hashlib
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from .engine import workspace
from .studio import authorize

router = APIRouter(prefix="/api/index", tags=["index"])
SKIP = {".git", ".agent", "node_modules", "target", "dist", "build",
        ".venv", "__pycache__", "vendor", ".next", "coverage"}
EXTENSIONS = {".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".go", ".java",
              ".cpp", ".hpp", ".c", ".h", ".cs", ".sql", ".md", ".json",
              ".yaml", ".yml", ".toml", ".html", ".css", ".sh"}
MAX_FILE_BYTES = 1_000_000
CHUNK_LINES = 80

class Request(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    max_files: int = Field(default=10000, ge=1, le=200000)

class Query(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=30, ge=1, le=100)

def db(project):
    path = workspace(project) / ".agent" / "index.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, hash TEXT NOT NULL, lines INTEGER NOT NULL DEFAULT 0)")
    # Migrate existing installations created with an earlier two-column schema.
    columns = {r[1] for r in con.execute("PRAGMA table_info(files)")}
    if "lines" not in columns:
        con.execute("ALTER TABLE files ADD COLUMN lines INTEGER NOT NULL DEFAULT 0")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(path UNINDEXED,line UNINDEXED,body,tokenize='unicode61')")
    return con

def sources(root):
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not (Path(base) / d).is_symlink())
        for name in sorted(files):
            item = Path(base) / name
            if item.suffix.lower() in EXTENSIONS and not item.is_symlink():
                yield item

def index_project(project, max_files=10000):
    root = workspace(project)
    checked = set()
    count = 0
    updated = 0
    unchanged = 0
    skipped = 0
    removed = 0
    truncated = False
    with closing(db(project)) as con:
        with con:
            for item in sources(root):
                if count >= max_files:
                    truncated = True
                    break
                relative = item.relative_to(root).as_posix()
                checked.add(relative)
                count += 1
                try:
                    if item.stat().st_size > MAX_FILE_BYTES:
                        skipped += 1
                        # If a previously indexed file becomes too large, remove its stale text.
                        con.execute("DELETE FROM chunks WHERE path=?", (relative,))
                        con.execute("DELETE FROM files WHERE path=?", (relative,))
                        continue
                    data = item.read_bytes()
                    if b"\x00" in data:
                        raise UnicodeError("Binary file")
                    text = data.decode("utf-8")
                except (OSError, UnicodeError):
                    skipped += 1
                    con.execute("DELETE FROM chunks WHERE path=?", (relative,))
                    con.execute("DELETE FROM files WHERE path=?", (relative,))
                    continue
                checksum = hashlib.sha256(data).hexdigest()
                old = con.execute("SELECT hash FROM files WHERE path=?", (relative,)).fetchone()
                if old and old["hash"] == checksum:
                    unchanged += 1
                    continue
                lines = text.splitlines()
                con.execute("DELETE FROM chunks WHERE path=?", (relative,))
                con.executemany("INSERT INTO chunks(path,line,body) VALUES(?,?,?)",
                    [(relative, str(i + 1), "\n".join(lines[i:i + CHUNK_LINES]))
                     for i in range(0, len(lines), CHUNK_LINES)])
                con.execute("INSERT INTO files(path,hash,lines) VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET hash=excluded.hash,lines=excluded.lines",
                            (relative, checksum, len(lines)))
                updated += 1
            # Only fully enumerated scans may prune deleted files.
            if not truncated:
                for row in con.execute("SELECT path FROM files").fetchall():
                    if row["path"] not in checked:
                        con.execute("DELETE FROM chunks WHERE path=?", (row["path"],))
                        con.execute("DELETE FROM files WHERE path=?", (row["path"],))
                        removed += 1
            total_files, total_lines = con.execute("SELECT COUNT(*),COALESCE(SUM(lines),0) FROM files").fetchone()
        return {"scanned": count, "updated": updated, "unchanged": unchanged,
                "removed": removed, "skipped": skipped, "truncated": truncated,
                "indexed_files": total_files, "indexed_lines": total_lines,
                "max_files": max_files}

def search_project(project, query, limit=30):
    terms = re.findall(r"[^\W_]{2,}[\w]*", query, flags=re.UNICODE)[:12]
    if not terms:
        return []
    # Always quote tokens so user input cannot become FTS5 query operators.
    expression = " OR ".join('"' + item.replace('"', '""') + '"' for item in terms)
    with closing(db(project)) as con:
        rows = con.execute(
            "SELECT path,line,snippet(chunks,2,'[',']','...',20) AS excerpt,bm25(chunks) AS score "
            "FROM chunks WHERE chunks MATCH ? ORDER BY score LIMIT ?",
            (expression, limit)).fetchall()
    return [{"path": row["path"], "line": int(row["line"]),
             "excerpt": row["excerpt"], "score": round(row["score"], 5)}
            for row in rows]

@router.post("/refresh")
def refresh(body: Request, authorization: str | None = Header(default=None)):
    authorize(authorization)
    return index_project(body.project, body.max_files)

@router.post("/search")
def search(body: Query, authorization: str | None = Header(default=None)):
    authorize(authorization)
    return {"results": search_project(body.project, body.query, body.limit)}

@router.get("/{project}/stats")
def stats(project: str, authorization: str | None = Header(default=None)):
    authorize(authorization)
    with closing(db(project)) as con:
        row = con.execute("SELECT COUNT(*),COALESCE(SUM(lines),0) FROM files").fetchone()
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {"indexed_files": row[0], "indexed_lines": row[1], "chunks": chunks}
