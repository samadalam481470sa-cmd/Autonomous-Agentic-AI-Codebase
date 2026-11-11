"""Durable local job queue and always-on worker.

The worker runs while the owner's computer is on, using the local model (and
therefore the local GPU when llama.cpp is configured for it). It never starts
itself: the desktop app passes ``AGENT_WORKER_ENABLED=1``, an operator can run
``python -m services.api.worker``, or the control API can be started explicitly.
``/api/worker/stop`` is the persisted kill switch; ``/api/worker/pause`` stops
new work without changing the policy. Powering the machine off stops it
naturally, and no remote service is contacted.

Jobs live in SQLite so a crash or restart does not lose queued work. A job
handler is a normal callable receiving the decoded payload. Unknown kinds fail
with an explicit error rather than being silently dropped.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import platform
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import power
from .studio import authorize

POLICIES = ("always", "ac_only", "manual", "off")
JOB_KINDS = re.compile(r"^[a-z][a-z0-9_.-]{1,64}$")
HOURS = re.compile(r"^(\d{1,2})(?:-(\d{1,2}))?$")
STATUSES = ("queued", "running", "completed", "failed", "cancelled")
HANDLERS: dict[str, object] = {}
GPU_CACHE = {"at": 0.0, "value": None}


def db_path() -> Path:
    path = Path(os.getenv("WORKER_DB_PATH", "./database/worker.sqlite3")).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def now() -> int:
    return int(time.time())


def connect(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or db_path()), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(
      id TEXT PRIMARY KEY,
      kind TEXT NOT NULL,
      payload TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled')),
      priority INTEGER NOT NULL DEFAULT 100,
      attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3,
      next_run_at INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      started_at INTEGER,
      finished_at INTEGER,
      worker TEXT NOT NULL DEFAULT '',
      error TEXT NOT NULL DEFAULT '',
      result TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS idx_jobs_status_priority ON jobs(status,next_run_at,priority,created_at);
    CREATE TABLE IF NOT EXISTS worker_state(
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL,
      updated_at INTEGER NOT NULL);
    """)
    return con


def state_get(key, default=None, path=None):
    with closing(connect(path)) as con:
        row = con.execute("SELECT value FROM worker_state WHERE key=?", (key,)).fetchone()
        return default if row is None else row["value"]


def state_set(key, value, path=None):
    with closing(connect(path)) as con, con:
        con.execute(
            "INSERT INTO worker_state(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (str(key), str(value), now()),
        )


def _state_defaults():
    return {
        "enabled": os.getenv("AGENT_WORKER_ENABLED", "0"),
        "paused": "0",
        "policy": os.getenv("AGENT_WORKER_POLICY", "always"),
        "active_hours": os.getenv("AGENT_WORKER_ACTIVE_HOURS", "0-24"),
        "max_gpu_temp_c": os.getenv("AGENT_WORKER_MAX_GPU_TEMP_C", "85"),
    }


def load_state(path=None) -> dict:
    defaults = _state_defaults()
    with closing(connect(path)) as con:
        rows = con.execute("SELECT key,value FROM worker_state").fetchall()
    stored = {row["key"]: row["value"] for row in rows}
    defaults.update({key: stored[key] for key in defaults if key in stored})
    defaults["max_gpu_temp_c"] = str(defaults.get("max_gpu_temp_c", "85"))
    return defaults


def parse_hours(spec: str) -> tuple[int, int]:
    match = HOURS.fullmatch(str(spec or "").strip())
    if not match:
        raise ValueError("active_hours must look like 9-17, 22-7 or 0-24")
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) is not None else (start + 1) % 24
    if not (0 <= start <= 24 and 0 <= end <= 24):
        raise ValueError("active_hours values must be between 0 and 24")
    return start, end


def in_hours(hour: int, spec: str) -> bool:
    start, end = parse_hours(spec)
    hour = int(hour) % 24
    if start == end or (start == 0 and end == 24):
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def decide(*, enabled, paused, policy, active_hours, hour, on_ac,
           gpu_temperature_c, max_gpu_temp_c) -> tuple[bool, str]:
    """Pure scheduling decision, independent of clocks and hardware probes."""
    if str(enabled) != "1":
        return False, "disabled"
    if str(paused) == "1":
        return False, "paused"
    if policy not in POLICIES:
        return False, "invalid_policy"
    if policy == "off":
        return False, "policy_off"
    try:
        permitted = in_hours(hour, active_hours)
    except ValueError:
        return False, "invalid_active_hours"
    if not permitted:
        return False, "outside_active_hours"
    if policy == "ac_only" and on_ac is False:
        return False, "on_battery"
    if policy == "manual" and str(enabled) != "1":
        return False, "manual_disabled"
    if gpu_temperature_c is not None and max_gpu_temp_c is not None:
        if gpu_temperature_c >= max_gpu_temp_c:
            return False, "gpu_thermal_guard"
    return True, "running"


def cached_gpu(ttl=10) -> dict:
    if GPU_CACHE["value"] is None or time.monotonic() - GPU_CACHE["at"] > ttl:
        GPU_CACHE["value"] = power.gpu_status()
        GPU_CACHE["at"] = time.monotonic()
    return GPU_CACHE["value"]


def decision_for_now(path=None) -> tuple[bool, str, dict]:
    state = load_state(path)
    gpu = cached_gpu()
    power_now = power.power_state()
    try:
        max_temp = float(state["max_gpu_temp_c"])
    except (TypeError, ValueError):
        max_temp = 85.0
    allowed, reason = decide(
        enabled=state["enabled"], paused=state["paused"], policy=state["policy"],
        active_hours=state["active_hours"], hour=datetime.now().hour,
        on_ac=power_now.get("on_ac"), gpu_temperature_c=gpu.get("max_temperature_c"),
        max_gpu_temp_c=max_temp,
    )
    return allowed, reason, {"state": state, "gpu": gpu, "power": power_now}


def enqueue(kind, payload=None, *, priority=100, max_attempts=3,
            delay_seconds=0, path=None) -> dict:
    if not isinstance(kind, str) or not JOB_KINDS.fullmatch(kind):
        raise ValueError("Job kind must be 1-64 lowercase identifier characters")
    payload = payload if payload is not None else {}
    if not isinstance(payload, dict):
        raise ValueError("Job payload must be an object")
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded.encode("utf-8")) > 64_000:
        raise ValueError("Job payload exceeds 64 KB")
    priority = max(0, min(int(priority), 1000))
    max_attempts = max(1, min(int(max_attempts), 10))
    stamp = now()
    job_id = uuid.uuid4().hex
    with closing(connect(path)) as con, con:
        con.execute(
            "INSERT INTO jobs(id,kind,payload,status,priority,attempts,max_attempts,"
            "next_run_at,created_at,updated_at) VALUES(?,?,?,'queued',?,0,?,?,?,?)",
            (job_id, kind, encoded, priority, max_attempts,
             stamp + max(0, int(delay_seconds)), stamp, stamp),
        )
    return {"job_id": job_id, "kind": kind, "status": "queued", "priority": priority}


def _job(row) -> dict:
    if row is None:
        return None
    item = dict(row)
    try:
        item["payload"] = json.loads(item.get("payload") or "{}")
    except ValueError:
        item["payload"] = {}
    try:
        item["result"] = json.loads(item["result"]) if item.get("result") else None
    except ValueError:
        item["result"] = None
    return item


def claim(worker_id=None, path=None) -> dict | None:
    stamp = now()
    worker_id = worker_id or f"{platform.node()[:40]}-{os.getpid()}"
    with closing(connect(path)) as con:
        con.isolation_level = None
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute(
                "SELECT id FROM jobs WHERE status='queued' AND next_run_at<=? "
                "ORDER BY priority ASC, created_at ASC LIMIT 1",
                (stamp,),
            ).fetchone()
            if row is None:
                con.execute("COMMIT")
                return None
            updated = con.execute(
                "UPDATE jobs SET status='running',worker=?,started_at=?,updated_at=?,"
                "attempts=attempts+1 WHERE id=? AND status='queued'",
                (worker_id, stamp, stamp, row["id"]),
            ).rowcount
            if updated != 1:
                con.execute("COMMIT")
                return None
            fresh = con.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            con.execute("COMMIT")
            return _job(fresh)
        except Exception:
            con.execute("ROLLBACK")
            raise


def complete(job_id, result=None, path=None) -> bool:
    encoded = json.dumps(result, ensure_ascii=False, default=str) if result is not None else ""
    if len(encoded.encode("utf-8")) > 200_000:
        encoded = json.dumps({"truncated": True, "summary": str(result)[:5000]})
    with closing(connect(path)) as con, con:
        return con.execute(
            "UPDATE jobs SET status='completed',updated_at=?,finished_at=?,result=?,error='' "
            "WHERE id=? AND status='running'",
            (now(), now(), encoded, job_id),
        ).rowcount == 1


def fail(job_id, error, *, retry_delay=None, path=None) -> dict:
    message = str(error)[:2000]
    with closing(connect(path)) as con:
        con.isolation_level = None
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute(
                "SELECT attempts,max_attempts FROM jobs WHERE id=? AND status='running'",
                (job_id,),
            ).fetchone()
            if row is None:
                con.execute("ROLLBACK")
                return {"updated": False}
            attempts, max_attempts = int(row["attempts"]), int(row["max_attempts"])
            if attempts < max_attempts:
                delay = retry_delay if retry_delay is not None else min(5 * (2 ** (attempts - 1)), 300)
                con.execute(
                    "UPDATE jobs SET status='queued',updated_at=?,next_run_at=?,error=? WHERE id=?",
                    (now(), now() + max(0, int(delay)), message, job_id),
                )
                status = "queued"
            else:
                con.execute(
                    "UPDATE jobs SET status='failed',updated_at=?,finished_at=?,error=? WHERE id=?",
                    (now(), now(), message, job_id),
                )
                status = "failed"
            con.execute("COMMIT")
            return {"updated": True, "status": status, "attempts": attempts}
        except Exception:
            con.execute("ROLLBACK")
            raise


def cancel(job_id, path=None) -> bool:
    with closing(connect(path)) as con, con:
        return con.execute(
            "UPDATE jobs SET status='cancelled',updated_at=?,finished_at=?,"
            "error='cancelled by operator' WHERE id=? AND status IN ('queued','running')",
            (now(), now(), job_id),
        ).rowcount == 1


def recover(stale_seconds=1800, path=None) -> dict:
    cutoff = now() - max(30, int(stale_seconds))
    recovered = failed = 0
    with closing(connect(path)) as con:
        con.isolation_level = None
        con.execute("BEGIN IMMEDIATE")
        try:
            rows = con.execute(
                "SELECT id,attempts,max_attempts FROM jobs WHERE status='running' AND started_at<?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                if int(row["attempts"]) < int(row["max_attempts"]):
                    con.execute(
                        "UPDATE jobs SET status='queued',updated_at=?,worker='',"
                        "error='recovered after interrupted run' WHERE id=?",
                        (now(), row["id"]),
                    )
                    recovered += 1
                else:
                    con.execute(
                        "UPDATE jobs SET status='failed',updated_at=?,finished_at=?,"
                        "error='interrupted and out of retries' WHERE id=?",
                        (now(), now(), row["id"]),
                    )
                    failed += 1
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return {"requeued": recovered, "failed": failed}


def stats(path=None) -> dict:
    with closing(connect(path)) as con:
        counts = {status: 0 for status in STATUSES}
        for row in con.execute("SELECT status,COUNT(*) AS count FROM jobs GROUP BY status"):
            counts[row["status"]] = int(row["count"])
        oldest = con.execute(
            "SELECT created_at FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
    return {
        "counts": counts,
        "queued": counts["queued"],
        "running": counts["running"],
        "total": sum(counts.values()),
        "oldest_queued_at": oldest["created_at"] if oldest else None,
    }


def list_jobs(status=None, limit=50, path=None) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    query = "SELECT * FROM jobs"
    args = []
    if status:
        if status not in STATUSES:
            raise ValueError("Unknown job status")
        query += " WHERE status=?"
        args.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with closing(connect(path)) as con:
        return [_job(row) for row in con.execute(query, args)]


def register_handler(kind, handler):
    if not JOB_KINDS.fullmatch(str(kind)):
        raise ValueError("Invalid job kind")
    if not callable(handler):
        raise ValueError("Handler must be callable")
    HANDLERS[str(kind)] = handler


def resolve_handler(kind):
    if kind in HANDLERS:
        return HANDLERS[kind]
    if kind == "polyglot.solve":
        from .polyglot import run_solve_job
        return run_solve_job
    if kind == "polyglot.check":
        from .polyglot import run_check_job
        return run_check_job
    if kind == "agent.auto":
        from .orchestrator import auto_advance_job
        return auto_advance_job
    if kind == "noop":
        return lambda payload: {"ok": True, "payload": payload}
    raise KeyError(f"No handler is registered for job kind {kind}")


def tick(*, path=None, handlers=None, worker_id=None) -> dict:
    # Avoid GPU/power probes on every poll when there is nothing to do.
    if stats(path)["queued"] == 0:
        return {"ran": False, "reason": "queue_empty"}
    allowed, reason, context = decision_for_now(path)
    if not allowed:
        return {"ran": False, "reason": reason}
    job = claim(worker_id=worker_id, path=path)
    if job is None:
        return {"ran": False, "reason": "queue_empty"}
    handler = (handlers or {}).get(job["kind"])
    try:
        handler = handler or resolve_handler(job["kind"])
        result = handler(job["payload"])
        if inspect.isawaitable(result):
            result = asyncio.run(result)
    except Exception as exc:  # handler failures are recorded, never lost
        outcome = fail(job["id"], f"{type(exc).__name__}: {exc}", path=path)
        return {"ran": True, "job_id": job["id"], "kind": job["kind"],
                "status": outcome.get("status", "failed"),
                "error": f"{type(exc).__name__}: {exc}"}
    complete(job["id"], result, path=path)
    return {"ran": True, "job_id": job["id"], "kind": job["kind"], "status": "completed"}


def status() -> dict:
    allowed, reason, context = decision_for_now()
    runtime_info = runtime.status()
    return {
        "worker": runtime_info,
        "decision": {"allowed": allowed, "reason": reason},
        "state": context["state"],
        "gpu": context["gpu"],
        "power": context["power"],
        "queue": stats(),
        "recent": list_jobs(limit=10),
        "policies": list(POLICIES),
        "usage": (
            "Runs only while this computer is powered on. Pause, stop or change "
            "the policy from the control page; the local GPU is used only when the "
            "local model runtime is configured with it."
        ),
    }


class Runtime:
    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self.started_at = None
        self.poll_seconds = float(os.getenv("AGENT_WORKER_POLL_SECONDS", "5"))
        self._last = None

    def start(self, poll_seconds=None):
        if poll_seconds is not None:
            self.poll_seconds = max(0.2, min(float(poll_seconds), 3600))
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self.started_at = now()
        self._thread = threading.Thread(target=self._loop, name="agent-worker", daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._last = tick()
            except Exception as exc:  # keep the supervisor alive
                self._last = {"ran": False, "reason": f"tick_error: {type(exc).__name__}"}
            self._stop.wait(self.poll_seconds)

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self.started_at = None

    def status(self):
        return {
            "thread_running": bool(self._thread and self._thread.is_alive()),
            "started_at": self.started_at,
            "poll_seconds": self.poll_seconds,
            "last_tick": self._last,
            "worker_id": f"{platform.node()[:40]}-{os.getpid()}",
        }


runtime = Runtime()


def maybe_start() -> bool:
    if os.getenv("AGENT_WORKER_ENABLED") == "1":
        recover()
        return runtime.start()
    return False


def run_forever(poll_seconds=5):
    """Standalone entry point: python -m services.api.worker."""
    recover()
    runtime.poll_seconds = max(0.2, float(poll_seconds))
    runtime.started_at = now()
    runtime._loop()


router = APIRouter(prefix="/api/worker", tags=["worker"])


class JobRequest(BaseModel):
    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,64}$")
    payload: dict = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=1000)
    max_attempts: int = Field(default=3, ge=1, le=10)


class PolicyRequest(BaseModel):
    policy: str | None = None
    active_hours: str | None = None
    max_gpu_temp_c: int | None = Field(default=None, ge=30, le=110)


def _autonomy():
    return os.getenv("AGENT_AUTONOMY") == "1"


@router.get("/status")
def worker_status(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return status()


@router.post("/jobs")
def create_job(body: JobRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        return enqueue(body.kind, body.payload, priority=body.priority,
                       max_attempts=body.max_attempts)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/jobs")
def jobs(status_filter: str | None = None, limit: int = 50,
         authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        return {"jobs": list_jobs(status_filter, limit), "queue": stats()}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, authorization: str | None = Header(default=None)):
    authorize(authorization)
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(400, "Invalid job id")
    if not cancel(job_id):
        raise HTTPException(409, "Job is not queued or running")
    return {"cancelled": True, "job_id": job_id}


@router.post("/pause")
def pause_worker(authorization: str | None = Header(default=None)):
    authorize(authorization)
    state_set("paused", "1")
    return {"paused": True}


@router.post("/resume")
def resume_worker(authorization: str | None = Header(default=None)):
    authorize(authorization)
    state_set("paused", "0")
    return {"paused": False}


@router.post("/stop")
def stop_worker(authorization: str | None = Header(default=None)):
    authorize(authorization)
    state_set("enabled", "0")
    return {"enabled": False, "note": "Persisted kill switch; queued jobs are retained."}


@router.post("/start")
def start_worker(authorization: str | None = Header(default=None)):
    authorize(authorization)
    state_set("enabled", "1")
    state_set("paused", "0")
    started = runtime.start()
    return {"enabled": True, "thread_started": started}


@router.post("/policy")
def update_policy(body: PolicyRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    if body.policy is not None:
        if body.policy not in POLICIES:
            raise HTTPException(400, "policy must be one of " + ", ".join(POLICIES))
        state_set("policy", body.policy)
    if body.active_hours is not None:
        try:
            parse_hours(body.active_hours)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        state_set("active_hours", body.active_hours)
    if body.max_gpu_temp_c is not None:
        state_set("max_gpu_temp_c", str(body.max_gpu_temp_c))
    return load_state()


@router.post("/tick")
def tick_now(authorization: str | None = Header(default=None),
             x_confirm_execution: str | None = Header(default=None)):
    authorize(authorization)
    if not _autonomy() and x_confirm_execution != "approve":
        raise HTTPException(428, "Explicit approval required to execute a queued job")
    return tick()


if __name__ == "__main__":  # pragma: no cover - manual entry point
    run_forever()
