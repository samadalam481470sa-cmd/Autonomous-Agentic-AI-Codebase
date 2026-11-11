"""Human-approved command execution.

This is the per-request trust mechanism the blanket ``ALLOW_COMMANDS`` switch
lacked. A command is recorded as a pending request with a digest over its exact
argv, then runs only after the operator approves that digest. Execution is
argv-only, never a shell, restricted to an executable allowlist, and every
request and decision is auditable through the stored row.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import toolchains
from .engine import db, workspace
from .studio import authorize

router = APIRouter(prefix="/api/execution/command", tags=["commands"])

ALLOWED_EXECUTABLES = {
    "python", "python3", "py", "pytest", "node", "npm", "npx", "tsc", "eslint",
    "ruff", "mypy", "cargo", "go", "dotnet", "java", "mvn", "gradle", "make",
    "git", "bundle", "ruby", "php", "swift", "dart", "deno", "bun", "uv",
}
GIT_DENIED = {"push", "reset", "clean", "rebase", "filter-branch", "remote",
              "config", "credential", "update-ref", "reflog"}
MAX_ARGS = 32
MAX_ARG_CHARS = 300
MAX_TIMEOUT = 300
DEFAULT_TIMEOUT = 120
MAX_OUTPUT = 8_000
FORBIDDEN = set(";|&$`<>\n\r\x00")
NOTE = ("Commands run on this computer, not in a sandbox. Review the exact argv "
        "before approving.")


class CommandRequest(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    argv: list[str] = Field(min_length=1, max_length=MAX_ARGS)
    reason: str = Field(default="", max_length=400)
    timeout_seconds: int = Field(default=DEFAULT_TIMEOUT, ge=5, le=MAX_TIMEOUT)


class DecisionRequest(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    approve: bool = True
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def initialize(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS command_requests (
            id TEXT PRIMARY KEY,
            project TEXT NOT NULL,
            argv TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            digest TEXT NOT NULL,
            status TEXT NOT NULL,
            timeout_seconds INTEGER NOT NULL,
            exit_code INTEGER,
            output TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            decided_at TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_command_requests_project
        ON command_requests(project, created_at DESC)
    """)


def validate(argv) -> list[str]:
    """Return a normalized argv list, or raise ValueError."""
    if not isinstance(argv, (list, tuple)) or not argv or len(argv) > MAX_ARGS:
        raise ValueError("argv must be a list of 1 to %d arguments" % MAX_ARGS)
    normalized = []
    for part in argv:
        if not isinstance(part, str) or not part or len(part) > MAX_ARG_CHARS:
            raise ValueError("each argument must be a short string")
        if any(character in FORBIDDEN for character in part):
            raise ValueError("shell metacharacters are not allowed")
        normalized.append(part)
    executable = Path(normalized[0]).name.lower()
    if executable.endswith(".exe"):
        executable = executable[:-4]
    if executable not in ALLOWED_EXECUTABLES:
        raise ValueError("executable is not allowlisted: " + executable)
    if executable == "git":
        subcommand = normalized[1].lower() if len(normalized) > 1 else ""
        if subcommand in GIT_DENIED:
            raise ValueError("git " + subcommand + " is not allowed from an agent")
        if any(item in ("--force", "-f") for item in normalized[1:3]):
            raise ValueError("force flags are not allowed")
    if "--force" in normalized:
        raise ValueError("force flags are not allowed")
    normalized[0] = executable
    return normalized


def digest_for(project: str, argv: list[str], reason: str) -> str:
    payload = json.dumps({"project": project, "argv": argv, "reason": reason},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def request(project: str, argv, reason: str = "", timeout_seconds: int = DEFAULT_TIMEOUT) -> dict:
    workspace(project)
    normalized = validate(argv)
    reason = str(reason or "")[:400]
    timeout = max(5, min(int(timeout_seconds), MAX_TIMEOUT))
    identifier = uuid.uuid4().hex
    digest = digest_for(project, normalized, reason)
    with db() as conn:
        initialize(conn)
        conn.execute(
            "INSERT INTO command_requests(id,project,argv,reason,digest,status,timeout_seconds)"
            " VALUES(?,?,?,?,?,?,?)",
            (identifier, project, json.dumps(normalized), reason, digest, "pending", timeout),
        )
    return {"request_id": identifier, "project": project, "argv": normalized,
            "reason": reason, "digest": digest, "timeout_seconds": timeout,
            "status": "pending", "note": NOTE}


def pending(project: str, limit: int = 20) -> list[dict]:
    with db() as conn:
        initialize(conn)
        rows = conn.execute(
            "SELECT id,argv,reason,digest,status,timeout_seconds,created_at,exit_code"
            " FROM command_requests WHERE project=? ORDER BY created_at DESC,id DESC LIMIT ?",
            (project, max(1, min(int(limit), 50))),
        ).fetchall()
    return [{"request_id": row[0], "argv": json.loads(row[1]), "reason": row[2],
             "digest": row[3], "status": row[4], "timeout_seconds": row[5],
             "created_at": row[6], "exit_code": row[7]} for row in rows]


def decide(project: str, request_id: str, approve: bool, expected_digest: str) -> dict:
    workspace(project)
    with db() as conn:
        initialize(conn)
        row = conn.execute(
            "SELECT argv,reason,digest,status,timeout_seconds FROM command_requests"
            " WHERE id=? AND project=?",
            (request_id, project),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Command request not found for this project")
        argv, reason, digest, status, timeout = json.loads(row[0]), row[1], row[2], row[3], row[4]
        if status != "pending":
            raise HTTPException(409, "Command request is no longer pending")
        if not hmac.compare_digest(expected_digest, digest):
            raise HTTPException(409, "Approval digest does not match this request")
        if not approve:
            conn.execute(
                "UPDATE command_requests SET status='rejected', decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                " WHERE id=?", (request_id,),
            )
            return {"request_id": request_id, "status": "rejected", "argv": argv}

    try:
        result = toolchains.run_argv(argv, cwd=workspace(project), timeout=timeout)
    except (ValueError, OSError) as error:
        raise HTTPException(400, "Command could not start: " + str(error))

    output = (result["stdout"] + "\n" + result["stderr"]).strip()[:MAX_OUTPUT]
    final = "succeeded" if result["exit_code"] == 0 and not result["timed_out"] else "failed"
    with db() as conn:
        initialize(conn)
        conn.execute(
            "UPDATE command_requests SET status=?, exit_code=?, output=?,"
            " decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (final, result["exit_code"], output, request_id),
        )
    return {
        "request_id": request_id, "status": final, "argv": argv,
        "exit_code": result["exit_code"], "timed_out": result["timed_out"],
        "duration_ms": result["duration_ms"], "stdout": result["stdout"],
        "stderr": result["stderr"], "output": output,
    }


@router.post("/request")
def create_request(body: CommandRequest,
                   authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        return request(body.project, body.argv, body.reason, body.timeout_seconds)
    except ValueError as error:
        raise HTTPException(400, str(error))


@router.get("/pending/{project}")
def list_pending(project: str, authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        workspace(project)
    except ValueError as error:
        raise HTTPException(400, str(error))
    return {"project": project, "requests": pending(project)}


@router.post("/decide")
def decide_request(body: DecisionRequest,
                   authorization: str | None = Header(default=None),
                   x_confirm_change: str | None = Header(default=None)):
    authorize(authorization)
    if x_confirm_change != "approve":
        raise HTTPException(428, "Explicit human approval required")
    return decide(body.project, body.request_id, body.approve, body.expected_digest)
