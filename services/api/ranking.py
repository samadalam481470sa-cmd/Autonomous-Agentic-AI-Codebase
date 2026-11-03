"""Online feedback learning for retrieval ranking.

Every relevant/not-relevant vote in the UI is stored in the project's local
SQLite database. Paths are scored with a Beta-smoothed acceptance ratio and a
30-day half-life, producing a bounded bonus or penalty that is added to the
fused hybrid retrieval score.

This is example-based online learning-to-rank: no training job, model file,
GPU or network. Votes are scoped to one project and cannot reference paths
outside the workspace.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing

from .engine import safe_path, workspace

RATINGS = {"up", "down"}
HALF_LIFE_DAYS = 30.0


def _db(project: str) -> sqlite3.Connection:
    path = workspace(project) / ".agent" / "semantic.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """CREATE TABLE IF NOT EXISTS sem_feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        line INTEGER NOT NULL DEFAULT 1,
        query TEXT NOT NULL DEFAULT '',
        rating TEXT NOT NULL CHECK(rating IN ('up','down')),
        created_at INTEGER NOT NULL)"""
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_sem_feedback_path ON sem_feedback(path,created_at DESC)"
    )
    return con


def weight() -> float:
    """Maximum absolute score contribution of the learned signal."""
    try:
        value = float(os.getenv("SEMANTIC_FEEDBACK_WEIGHT", "0.02"))
    except (TypeError, ValueError):
        value = 0.02
    return max(0.0, min(value, 0.25))


def record(project: str, query: str, path: str, line: int, rating: str) -> dict:
    if rating not in RATINGS:
        raise ValueError("rating must be up or down")
    target = safe_path(project, path)
    if not target.is_file():
        raise ValueError("Feedback must reference an existing project file")
    query = (query or "").strip()[:500]
    with closing(_db(project)) as con, con:
        con.execute(
            "INSERT INTO sem_feedback(path,line,query,rating,created_at) VALUES(?,?,?,?,?)",
            (path, max(1, min(int(line), 10_000_000)), query, rating, int(time.time())),
        )
    return summary(project)


def _decay(created_at: int, now: int) -> float:
    age_days = max(0.0, (now - created_at) / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def boost_map(project: str) -> dict[str, float]:
    """Smoothed, decayed relevance in [-1, 1] per path. Missing paths score 0."""
    now = int(time.time())
    positive: dict[str, float] = {}
    negative: dict[str, float] = {}
    try:
        with closing(_db(project)) as con:
            rows = con.execute("SELECT path,rating,created_at FROM sem_feedback").fetchall()
    except (sqlite3.Error, OSError):
        return {}
    for row in rows:
        decay = _decay(int(row["created_at"]), now)
        bucket = positive if row["rating"] == "up" else negative
        bucket[row["path"]] = bucket.get(row["path"], 0.0) + decay
    boosts = {}
    for path in set(positive) | set(negative):
        up = positive.get(path, 0.0)
        down = negative.get(path, 0.0)
        # Beta(1,1) prior keeps a single vote from dominating the ranking.
        probability = (up + 1.0) / (up + down + 2.0)
        boosts[path] = 2.0 * probability - 1.0
    return boosts


def summary(project: str) -> dict:
    try:
        with closing(_db(project)) as con:
            rows = con.execute(
                "SELECT rating,COUNT(*) AS total FROM sem_feedback GROUP BY rating"
            ).fetchall()
            paths = con.execute("SELECT COUNT(DISTINCT path) FROM sem_feedback").fetchone()[0]
            recent = con.execute(
                "SELECT path,line,rating,created_at FROM sem_feedback "
                "ORDER BY id DESC LIMIT 10"
            ).fetchall()
    except (sqlite3.Error, OSError):
        return {"positive": 0, "negative": 0, "paths": 0, "weight": weight(),
                "half_life_days": HALF_LIFE_DAYS, "recent": []}
    counts = {row["rating"]: row["total"] for row in rows}
    return {
        "positive": int(counts.get("up", 0)),
        "negative": int(counts.get("down", 0)),
        "paths": int(paths),
        "weight": weight(),
        "half_life_days": HALF_LIFE_DAYS,
        "recent": [dict(row) for row in recent],
    }
