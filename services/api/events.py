"""Append-only run event log.

Runs, the dashboard, resume, audit and the learning loop read from this log.
Events are never updated or deleted: SQLite triggers reject both operations.
Sequences are allocated per run inside ``BEGIN IMMEDIATE`` so concurrent
writers cannot duplicate or reorder an event.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_.]{2,64}$")
SECRET_KEY = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization|credential)", re.I)
MAX_PAYLOAD_BYTES = 64_000


def db_path() -> Path:
    path = Path(os.getenv("EVENT_DB_PATH", "./database/events.sqlite3")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or db_path()), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS run_events(
      run_id TEXT NOT NULL,
      sequence INTEGER NOT NULL,
      schema_version INTEGER NOT NULL,
      type TEXT NOT NULL,
      actor TEXT NOT NULL,
      created_at TEXT NOT NULL,
      payload TEXT NOT NULL,
      PRIMARY KEY(run_id,sequence));
    CREATE INDEX IF NOT EXISTS idx_run_events_type ON run_events(type,created_at DESC);
    CREATE TRIGGER IF NOT EXISTS run_events_append_only_update
      BEFORE UPDATE ON run_events
      BEGIN SELECT RAISE(ABORT, 'run_events is append-only'); END;
    CREATE TRIGGER IF NOT EXISTS run_events_append_only_delete
      BEFORE DELETE ON run_events
      BEGIN SELECT RAISE(ABORT, 'run_events is append-only'); END;
    """)
    return con


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def redact(value, depth=0):
    """Remove credential-shaped keys before an event is persisted."""
    if depth > 8:
        return "[depth-limit]"
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key)
            if SECRET_KEY.search(name):
                result[name] = "[redacted]"
            else:
                result[name] = redact(item, depth + 1)
        return result
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return value[:20_000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:2000]


def append(run_id, event_type, actor="system", payload=None, *, path=None) -> dict:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run id")
    if not isinstance(event_type, str) or not EVENT_TYPE.fullmatch(event_type):
        raise ValueError("Invalid event type")
    actor = str(actor or "system")[:64]
    raw = payload if isinstance(payload, dict) else {}
    if len(json.dumps(raw, ensure_ascii=False, default=str).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("Event payload exceeds 64 KB")
    safe = redact(raw)
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("Event payload exceeds 64 KB")
    created = timestamp()
    with closing(connect(path)) as con:
        con.isolation_level = None
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM run_events WHERE run_id=?", (run_id,)
            ).fetchone()
            sequence = int(row[0]) + 1
            con.execute(
                "INSERT INTO run_events(run_id,sequence,schema_version,type,actor,created_at,payload) "
                "VALUES(?,?,?,?,?,?,?)",
                (run_id, sequence, SCHEMA_VERSION, event_type, actor, created, encoded),
            )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return {
        "schema_version": SCHEMA_VERSION, "run_id": run_id, "sequence": sequence,
        "type": event_type, "actor": actor, "created_at": created,
        "payload": safe,
    }


def _event(row) -> dict:
    try:
        payload = json.loads(row["payload"])
    except ValueError:
        payload = {}
    return {
        "schema_version": row["schema_version"], "run_id": row["run_id"],
        "sequence": row["sequence"], "type": row["type"], "actor": row["actor"],
        "created_at": row["created_at"], "payload": payload,
    }


def list_events(run_id, after=0, limit=1000, path=None) -> list[dict]:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run id")
    limit = max(1, min(int(limit), 5000))
    with closing(connect(path)) as con:
        rows = con.execute(
            "SELECT * FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
            (run_id, max(0, int(after)), limit),
        ).fetchall()
    return [_event(row) for row in rows]


def latest_sequence(run_id, path=None) -> int:
    with closing(connect(path)) as con:
        row = con.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM run_events WHERE run_id=?", (run_id,)
        ).fetchone()
    return int(row[0])


def replay(run_id, path=None) -> dict:
    items = list_events(run_id, 0, 5000, path)
    sequences = [item["sequence"] for item in items]
    contiguous = sequences == list(range(1, len(sequences) + 1))
    return {"run_id": run_id, "events": items, "count": len(items), "contiguous": contiguous}


def encode_sse(event: dict) -> str:
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['sequence']}\nevent: {event['type']}\ndata: {data}\n\n"


async def tail(run_id, after=0, *, poll_seconds=0.4, max_seconds=300, path=None):
    """Yield SSE frames for new events, including a heartbeat every ten seconds."""
    started = time.monotonic()
    cursor = max(0, int(after))
    idle = 0.0
    while time.monotonic() - started < max_seconds:
        batch = await asyncio.to_thread(list_events, run_id, cursor, 500, path)
        if batch:
            for item in batch:
                cursor = item["sequence"]
                yield encode_sse(item)
            idle = 0.0
            continue
        await asyncio.sleep(poll_seconds)
        idle += poll_seconds
        if idle >= 10:
            idle = 0.0
            yield ": heartbeat\n\n"
