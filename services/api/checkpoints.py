"""Durable, local SQLite checkpoints for explicitly approved Studio writes.

A checkpoint is created *before* replacing a file, and only restores when the
file still matches the corresponding applied version. Original bytes are kept
in SQLite; no cloud account or remote database is used.
"""
import hashlib
import sqlite3
import uuid
from fastapi import HTTPException
from .engine import db

MAX_CONTENT_BYTES = 200_000

def sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def initialize(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_checkpoints (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            path TEXT NOT NULL,
            previous_content TEXT NOT NULL,
            previous_exists INTEGER NOT NULL CHECK(previous_exists IN (0,1)),
            applied_sha256 TEXT NOT NULL,
            applied_exists INTEGER NOT NULL CHECK(applied_exists IN (0,1)),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_file_checkpoints_history
        ON file_checkpoints(project,path,created_at DESC,id DESC)
    """)

def snapshot(
    project: str, path: str, previous: str, previous_exists: bool,
    applied: str, applied_exists: bool = True
) -> str:
    """Persist the pre-edit version; callers must subsequently apply the edit."""
    if max(len(previous.encode("utf-8")), len(applied.encode("utf-8"))) > MAX_CONTENT_BYTES:
        raise HTTPException(413, "File exceeds checkpoint size limit")
    if not previous_exists and previous:
        raise ValueError("Nonexistent file cannot have previous contents")
    if not applied_exists and applied:
        raise ValueError("Deleted file cannot have applied contents")
    checkpoint_id = uuid.uuid4().hex
    with db() as conn:
        initialize(conn)
        conn.execute(
            """INSERT INTO file_checkpoints
            (id,project,path,previous_content,previous_exists,applied_sha256,applied_exists)
            VALUES(?,?,?,?,?,?,?)""",
            (checkpoint_id, project, path, previous, int(previous_exists),
             sha256(applied), int(applied_exists)),
        )
    return checkpoint_id

def one(project: str, path: str, checkpoint_id: str) -> dict:
    with db() as conn:
        initialize(conn)
        result = conn.execute(
            """SELECT id,previous_content,previous_exists,applied_sha256,applied_exists
            FROM file_checkpoints WHERE id=? AND project=? AND path=?""",
            (checkpoint_id, project, path),
        ).fetchone()
    if result is None:
        raise HTTPException(404, "Checkpoint not found for this project and file")
    return dict(zip(
        ("id", "previous_content", "previous_exists", "applied_sha256", "applied_exists"),
        result,
    ))

def recent(project: str, path: str, limit: int = 15) -> list[dict]:
    with db() as conn:
        initialize(conn)
        rows = conn.execute(
            """SELECT id,created_at,previous_exists,applied_sha256,applied_exists
            FROM file_checkpoints WHERE project=? AND path=?
            ORDER BY created_at DESC,id DESC LIMIT ?""",
            (project, path, min(max(limit,1),50)),
        ).fetchall()
    return [dict(zip(
        ("id", "created_at", "previous_exists", "applied_sha256", "applied_exists"), r
    )) for r in rows]
