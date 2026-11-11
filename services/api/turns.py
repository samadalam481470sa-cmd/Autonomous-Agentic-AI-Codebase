"""Turn-level undo.

Approved edits already write per-file checkpoints. This module groups the
checkpoints written by one assistant turn so the operator can revert a whole
turn (``revert this message``) instead of file by file. Each revert writes its
own inverse checkpoint, so an undo can itself be undone.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import checkpoints
from .engine import db

router = APIRouter(prefix="/api/studio/turns", tags=["turns"])


def initialize(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS turn_edits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id TEXT NOT NULL,
            project TEXT NOT NULL,
            path TEXT NOT NULL,
            checkpoint_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_turn_edits_project
        ON turn_edits(project, turn_id, id)
    """)


def new_turn() -> str:
    return uuid.uuid4().hex


def record(project: str, turn_id: str, path: str, checkpoint_id: str) -> None:
    with db() as conn:
        initialize(conn)
        conn.execute(
            "INSERT INTO turn_edits(turn_id,project,path,checkpoint_id) VALUES(?,?,?,?)",
            (turn_id, project, path, checkpoint_id),
        )


def edits(project: str, turn_id: str) -> list[dict]:
    with db() as conn:
        initialize(conn)
        rows = conn.execute(
            "SELECT path, checkpoint_id FROM turn_edits"
            " WHERE project=? AND turn_id=? ORDER BY id ASC",
            (project, turn_id),
        ).fetchall()
    return [{"path": path, "checkpoint_id": checkpoint} for path, checkpoint in rows]


def recent(project: str, limit: int = 10) -> list[dict]:
    with db() as conn:
        initialize(conn)
        rows = conn.execute(
            "SELECT turn_id, MIN(created_at), COUNT(*), GROUP_CONCAT(path)"
            " FROM turn_edits WHERE project=? GROUP BY turn_id"
            " ORDER BY MAX(id) DESC LIMIT ?",
            (project, max(1, min(int(limit), 50))),
        ).fetchall()
    return [{"turn_id": turn, "created_at": created, "files": int(count or 0),
             "paths": str(paths or "").split(",") if paths else []}
            for turn, created, count, paths in rows]


def latest(project: str):
    with db() as conn:
        initialize(conn)
        row = conn.execute(
            "SELECT turn_id FROM turn_edits WHERE project=? ORDER BY id DESC LIMIT 1",
            (project,),
        ).fetchone()
    return row[0] if row else None


def revert(project: str, turn_id=None) -> dict:
    """Restore every file in a turn, newest edit first.

    A file that changed after the turn is skipped rather than overwritten, so a
    stale undo can never discard newer work.
    """
    from .studio import WRITE_LOCK, atomic_text_write, current, digest, resolve

    target_turn = turn_id or latest(project)
    if not target_turn:
        raise HTTPException(404, "No recorded edits to revert for this project")
    rows = edits(project, target_turn)
    if not rows:
        raise HTTPException(404, "Turn not found for this project")

    reverted = []
    skipped = []
    with WRITE_LOCK:
        for row in reversed(rows):
            path = row["path"]
            try:
                target = resolve(project, path)
                data = checkpoints.one(project, path, row["checkpoint_id"])
                content = current(target)
                exists = target.is_file()
                if (digest(content) != data["applied_sha256"]
                        or exists != bool(data["applied_exists"])):
                    skipped.append({"path": path, "reason": "changed since the edit"})
                    continue
                undo_id = checkpoints.snapshot(
                    project, path, content, exists, data["previous_content"],
                    bool(data["previous_exists"]),
                )
                if data["previous_exists"]:
                    atomic_text_write(target, data["previous_content"])
                else:
                    target.unlink(missing_ok=True)
                reverted.append({"path": path, "undo_checkpoint_id": undo_id})
            except HTTPException as error:
                skipped.append({"path": path, "reason": str(error.detail)})
            except (OSError, ValueError) as error:
                skipped.append({"path": path, "reason": str(error)})
    return {"turn_id": target_turn, "reverted": reverted, "skipped": skipped,
            "files_reverted": len(reverted)}


class RevertRequest(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    turn_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


@router.get("/{project}")
def list_turns(project: str, authorization: str | None = Header(default=None)):
    # Imported lazily: studio imports this module to record turn edits.
    from .studio import authorize
    authorize(authorization)
    return {"project": project, "turns": recent(project)}


@router.post("/revert")
def revert_turn(body: RevertRequest,
                authorization: str | None = Header(default=None),
                x_confirm_change: str | None = Header(default=None)):
    from .studio import authorize
    authorize(authorization)
    if x_confirm_change != "approve":
        raise HTTPException(428, "Explicit human approval required")
    return revert(body.project, body.turn_id)
