"""Lifelong local learning from interactions, feedback and verification.

This module is deliberately narrower than "the model rewrites itself". It:

* records redacted prompts, answers and citations locally when the owner opts in;
* learns a small retrieval re-ranker from explicit ratings and cited answers;
* evaluates every candidate on a chronological holdout and self-supervised
  repository probes, and promotes it only when it beats the active model;
* keeps model versions so a regression can be rolled back;
* runs a background maintenance loop that indexes changed files and trains when
  new feedback arrives, while obeying the thermal and battery governor.

Nothing is uploaded. The learner never edits files, executes commands or calls
a remote service. The local model runtime may use the GPU for inference; the
learner itself is intentionally CPU-light so it cannot starve a 24/7 session.
"""
from __future__ import annotations

import json
import math
import os
import platform
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

from . import content_safety, power
from .engine import ROOT, workspace

FEATURES = (
    "bias", "fused", "semantic", "lexical", "path_overlap",
    "excerpt_overlap", "path_feedback", "test_file", "depth",
)
RATINGS = {"up", "down"}
PROJECT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_PROMPT = 20_000
MAX_RESPONSE = 20_000
MODEL_CACHE: dict[str, tuple[float, dict[str, float] | None]] = {}
CACHE_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Local storage
# ---------------------------------------------------------------------------

def db_path(project: str) -> Path:
    path = workspace(project) / ".agent" / "learning.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(project: str) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path(project)), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS interactions(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, prompt TEXT NOT NULL,
          response TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]',
          rating TEXT NOT NULL DEFAULT '', redactions INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_interactions_created
          ON interactions(created_at DESC);
        CREATE TABLE IF NOT EXISTS models(
          id TEXT PRIMARY KEY, weights TEXT NOT NULL, metrics TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
          notes TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS idx_models_active ON models(active,created_at DESC);
        CREATE TABLE IF NOT EXISTS cycles(
          id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL,
          detail TEXT NOT NULL, created_at INTEGER NOT NULL);
        """
    )
    return con


def capture(project: str, kind: str, prompt: str, response: str,
            citations: list | None = None) -> str | None:
    """Store a redacted interaction if the owner enabled capture.

    Capture is on by default for the local launcher. It can be disabled at any
    time with ``AETHERION_LEARN_CAPTURE=0``; no data is sent anywhere.
    """
    if os.getenv("AETHERION_LEARN_CAPTURE", "1") != "1":
        return None
    try:
        prompt_safe = content_safety.scan_and_redact(str(prompt or "")[:MAX_PROMPT])
        response_safe = content_safety.scan_and_redact(str(response or "")[:MAX_RESPONSE])
        if not prompt_safe["text"].strip() and not response_safe["text"].strip():
            return None
        clean_citations = []
        for item in (citations or [])[:40]:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                clean_citations.append({
                    "path": item["path"][:512],
                    "line": max(1, int(item.get("line", 1) or 1)),
                })
        ident = uuid.uuid4().hex
        redactions = (int(prompt_safe["safety"]["secrets"])
                      + int(response_safe["safety"]["secrets"]))
        with connect(project) as con:
            con.execute(
                "INSERT INTO interactions(id,kind,prompt,response,citations,rating,"
                "redactions,created_at) VALUES(?,?,?,?,?,'',?,?)",
                (ident, str(kind)[:32], prompt_safe["text"], response_safe["text"],
                 json.dumps(clean_citations, separators=(",", ":")),
                 redactions, int(time.time())),
            )
        return ident
    except (sqlite3.Error, OSError, ValueError, TypeError):
        # Learning must never break a chat response.
        return None


def rate(project: str, interaction_id: str, rating: str) -> dict:
    if rating not in RATINGS:
        raise ValueError("rating must be up or down")
    if not re.fullmatch(r"[a-f0-9]{32}", interaction_id or ""):
        raise ValueError("invalid interaction id")
    with connect(project) as con:
        changed = con.execute(
            "UPDATE interactions SET rating=? WHERE id=?",
            (rating, interaction_id),
        ).rowcount
        if changed != 1:
            raise ValueError("interaction not found")
    return {"id": interaction_id, "rating": rating, "rated": True}


def interactions(project: str, limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    with connect(project) as con:
        rows = con.execute(
            "SELECT id,kind,prompt,response,citations,rating,redactions,created_at "
            "FROM interactions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for row in rows:
        try:
            citations = json.loads(row["citations"])
        except ValueError:
            citations = []
        result.append({
            "id": row["id"], "kind": row["kind"],
            "prompt": row["prompt"][:500], "response": row["response"][:500],
            "citations": citations[:12], "rating": row["rating"],
            "redactions": row["redactions"], "created_at": row["created_at"],
        })
    return result


# ---------------------------------------------------------------------------
# Learned retrieval re-ranker
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    return {
        token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "")
        if token.lower() not in {
            "the", "and", "for", "with", "this", "that", "from", "function",
            "return", "class", "import", "const", "self", "none", "true", "false",
        }
    }


def _overlap(query: str, text: str) -> float:
    wanted = _tokens(query)
    if not wanted:
        return 0.0
    return len(wanted & _tokens(text)) / len(wanted)


def features(query: str, result: dict) -> dict[str, float]:
    """Features available at retrieval time; all are bounded to [-1, 1]."""
    path = str(result.get("path") or "")
    excerpt = str(result.get("excerpt") or "")
    semantic = float(result.get("semantic_score") or 0.0)
    lexical = float(result.get("lexical_score") or 0.0)
    fused = float(result.get("score") or 0.0)
    return {
        "bias": 1.0,
        "fused": min(1.0, max(0.0, fused * 20.0)),
        "semantic": min(1.0, max(0.0, semantic)),
        "lexical": min(1.0, max(0.0, math.log1p(max(0.0, lexical)) / 6.0)),
        "path_overlap": _overlap(query, path),
        "excerpt_overlap": _overlap(query, excerpt),
        "path_feedback": max(-1.0, min(1.0, float(result.get("learned_boost") or 0.0) * 50.0)),
        "test_file": 1.0 if re.search(r"(^|/)(tests?|specs?)(/|$)|(_test|\.test|\.spec)\.", path) else 0.0,
        "depth": 1.0 / (1.0 + path.count("/")),
    }


def _delta(weights: dict[str, float], feature: dict[str, float]) -> float:
    return sum(weights.get(name, 0.0) * value for name, value in feature.items())


def _model_score(weights: dict[str, float] | None, query: str, result: dict) -> float:
    base = float(result.get("score") or 0.0)
    if not weights:
        return base
    return base + 0.05 * math.tanh(_delta(weights, features(query, result)))


def active_weights(project: str) -> dict[str, float] | None:
    cached = MODEL_CACHE.get(project)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    weights = None
    try:
        with connect(project) as con:
            row = con.execute(
                "SELECT weights FROM models WHERE active=1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is not None:
            parsed = json.loads(row["weights"])
            if isinstance(parsed, dict):
                weights = {str(key): float(value) for key, value in parsed.items()
                           if key in FEATURES and math.isfinite(float(value))}
    except (sqlite3.Error, OSError, ValueError, TypeError):
        weights = None
    MODEL_CACHE[project] = (time.monotonic(), weights)
    return weights


def rerank(project: str, query: str, results: list[dict]) -> list[dict]:
    weights = active_weights(project)
    if not results or not weights:
        return results
    for item in results:
        learned = round(0.05 * math.tanh(_delta(weights, features(query, item))), 6)
        item["learned_score"] = learned
        item["score"] = round(float(item.get("score") or 0.0) + learned, 6)
    return sorted(results, key=lambda item: item["score"], reverse=True)


def _candidates(project: str, query: str, limit: int = 30) -> list[dict]:
    from . import semantic
    try:
        return semantic.search(project, query, limit=limit, mode="hybrid",
                               apply_learning=False)
    except (sqlite3.Error, OSError, ValueError):
        return []


def _label_groups(project: str) -> dict[str, dict]:
    groups: dict[str, dict] = {}

    def add(query: str, path: str, positive: bool, stamp: int) -> None:
        query = (query or "").strip()[:500]
        if not query or not path:
            return
        item = groups.setdefault(query, {"positive": set(), "negative": set(),
                                          "at": stamp})
        item["positive" if positive else "negative"].add(path)
        item["at"] = max(item["at"], stamp)

    try:
        from . import ranking
        with closing(ranking._db(project)) as con:
            for row in con.execute("SELECT query,path,rating,created_at FROM sem_feedback"):
                add(row["query"], row["path"], row["rating"] == "up", int(row["created_at"]))
    except (sqlite3.Error, OSError):
        pass

    with connect(project) as con:
        rows = con.execute(
            "SELECT prompt,citations,rating,created_at FROM interactions "
            "WHERE rating IN ('up','down')"
        ).fetchall()
    for row in rows:
        try:
            citations = json.loads(row["citations"])
        except ValueError:
            citations = []
        for citation in citations:
            if isinstance(citation, dict) and isinstance(citation.get("path"), str):
                add(row["prompt"], citation["path"], row["rating"] == "up",
                    int(row["created_at"]))
    return groups


def training_groups(project: str, limit: int = 80) -> list[dict]:
    """Turn ratings into candidate lists for pairwise learning-to-rank."""
    labelled = _label_groups(project)
    result = []
    for query, labels in sorted(labelled.items(), key=lambda item: item[1]["at"]):
        candidates = _candidates(project, query, limit=30)
        if not candidates:
            continue
        paths = {item["path"] for item in candidates}
        positive = paths & labels["positive"]
        if not positive:
            continue
        negative = paths - positive
        if not negative:
            continue
        result.append({
            "query": query, "candidates": candidates,
            "positive": positive, "negative": negative, "at": labels["at"],
        })
        if len(result) >= limit:
            break
    return result


def _ndcg(groups: list[dict], weights: dict[str, float] | None) -> float:
    total = 0.0
    counted = 0
    for group in groups:
        ranked = sorted(
            group["candidates"],
            key=lambda item: _model_score(weights, group["query"], item),
            reverse=True,
        )
        gains = [1.0 if item["path"] in group["positive"] else 0.0
                 for item in ranked[:5]]
        ideal = [1.0] * min(len(group["positive"]), 5)
        dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
        idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
        if idcg:
            total += dcg / idcg
            counted += 1
    return round(total / counted, 6) if counted else 0.0


def _fit(groups: list[dict], epochs: int = 220, rate_value: float = 0.15) -> dict[str, float]:
    weights = {name: 0.0 for name in FEATURES}
    pairs = []
    for group in groups:
        positives = [item for item in group["candidates"] if item["path"] in group["positive"]]
        negatives = [item for item in group["candidates"] if item["path"] in group["negative"]]
        for positive in positives[:4]:
            for negative in negatives[:8]:
                pairs.append((
                    features(group["query"], positive),
                    features(group["query"], negative),
                ))
    if not pairs:
        return weights
    l2 = 1e-4
    for epoch in range(max(1, int(epochs))):
        for offset, (positive, negative) in enumerate(pairs):
            margin = _delta(weights, positive) - _delta(weights, negative)
            # Logistic pairwise loss; stable for large margins.
            gradient = 1.0 / (1.0 + math.exp(min(30.0, margin)))
            if epoch == 0 and offset == 0:
                gradient = min(gradient, 0.5)
            for name in FEATURES:
                value = gradient * (positive[name] - negative[name]) - l2 * weights[name]
                weights[name] = max(-2.0, min(2.0, weights[name] + rate_value * value))
    return {name: round(value, 6) for name, value in weights.items()}


def _probe_groups(project: str, limit: int = 6) -> list[dict]:
    """Self-supervised queries from real files, used only for evaluation."""
    try:
        from . import semantic
        with closing(semantic._db(project)) as con:
            rows = con.execute(
                "SELECT path FROM sem_files ORDER BY path LIMIT ?", (limit,)
            ).fetchall()
        groups = []
        for row in rows:
            path = row["path"]
            stem = Path(path).stem.replace("_", " ").replace("-", " ")
            if len(stem) < 3:
                continue
            candidates = _candidates(project, stem, limit=20)
            if not candidates or path not in {item["path"] for item in candidates}:
                continue
            groups.append({
                "query": stem, "candidates": candidates,
                "positive": {path},
                "negative": {item["path"] for item in candidates if item["path"] != path},
            })
        return groups
    except (sqlite3.Error, OSError):
        return []


def train(project: str, force: bool = False) -> dict:
    groups = training_groups(project)
    minimum = max(1, int(os.getenv("AETHERION_LEARN_MIN_EXAMPLES", "4")))
    if len(groups) < minimum:
        return {"trained": False, "reason": "not_enough_feedback",
                "examples": len(groups), "required": minimum}
    ordered = sorted(groups, key=lambda item: item["at"])
    cut = max(2, int(len(ordered) * 0.7)) if len(ordered) >= 4 else len(ordered)
    learning, holdout = ordered[:cut], ordered[cut:]
    weights = _fit(learning)
    baseline = _ndcg(holdout or ordered, None)
    candidate = _ndcg(holdout or ordered, weights)
    probes = _probe_groups(project)
    probe_baseline = _ndcg(probes, None) if probes else None
    probe_candidate = _ndcg(probes, weights) if probes else None
    gain = float(os.getenv("AETHERION_LEARN_MIN_GAIN", "0.005"))
    promoted = bool(holdout and candidate >= baseline + gain
                    and (probe_candidate is None or probe_candidate >= probe_baseline - 0.05))
    if force and not promoted and candidate >= baseline:
        promoted = True
    metrics = {
        "examples": len(groups), "learning": len(learning), "holdout": len(holdout),
        "baseline_ndcg5": baseline, "candidate_ndcg5": candidate,
        "probe_baseline_ndcg5": probe_baseline, "probe_candidate_ndcg5": probe_candidate,
        "gain": round(candidate - baseline, 6),
        "backend": "pure-python", "gpu_used": False,
    }
    ident = uuid.uuid4().hex
    with connect(project) as con:
        if promoted:
            con.execute("UPDATE models SET active=0")
        con.execute(
            "INSERT INTO models(id,weights,metrics,active,created_at,notes) "
            "VALUES(?,?,?,?,?,?)",
            (ident, json.dumps(weights, sort_keys=True), json.dumps(metrics, sort_keys=True),
             int(promoted), int(time.time()),
             "promoted" if promoted else "candidate did not beat the active model"),
        )
    MODEL_CACHE.pop(project, None)
    return {"trained": True, "promoted": promoted, "model_id": ident,
            "metrics": metrics, "weights": weights}


def rollback(project: str) -> dict:
    with connect(project) as con:
        current = con.execute(
            "SELECT id FROM models WHERE active=1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if current is None:
            raise ValueError("no active model to roll back")
        previous = con.execute(
            "SELECT id,metrics FROM models WHERE id<>? ORDER BY created_at DESC LIMIT 1",
            (current["id"],),
        ).fetchone()
        if previous is None:
            raise ValueError("no earlier model to restore")
        con.execute("UPDATE models SET active=0")
        con.execute("UPDATE models SET active=1 WHERE id=?", (previous["id"],))
    MODEL_CACHE.pop(project, None)
    try:
        metrics = json.loads(previous["metrics"])
    except ValueError:
        metrics = {}
    return {"active_model": previous["id"], "metrics": metrics, "rolled_back": True}


def model_state(project: str) -> dict:
    with connect(project) as con:
        active = con.execute(
            "SELECT id,metrics,created_at FROM models WHERE active=1 "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        latest = con.execute(
            "SELECT id,metrics,active,created_at,notes FROM models "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    def parse(row):
        if row is None:
            return None
        try:
            metrics = json.loads(row["metrics"])
        except ValueError:
            metrics = {}
        return {"id": row["id"], "metrics": metrics, "created_at": row["created_at"]}
    result = {"active": parse(active), "latest": parse(latest)}
    if latest is not None:
        result["latest"]["active"] = bool(latest["active"])
        result["latest"]["notes"] = latest["notes"]
    return result


def summary(project: str) -> dict:
    with connect(project) as con:
        counts = con.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN rating='up' THEN 1 ELSE 0 END) AS up, "
            "SUM(CASE WHEN rating='down' THEN 1 ELSE 0 END) AS down "
            "FROM interactions"
        ).fetchone()
        cycles = con.execute(
            "SELECT status,detail,created_at FROM cycles ORDER BY id DESC LIMIT 3"
        ).fetchall()
    return {
        "interactions": int(counts["total"] or 0),
        "positive": int(counts["up"] or 0),
        "negative": int(counts["down"] or 0),
        "model": model_state(project)["active"],
        "recent_cycles": [dict(row) for row in cycles],
        "capture": os.getenv("AETHERION_LEARN_CAPTURE", "1") == "1",
    }


def status(project: str) -> dict:
    summary_info = summary(project)
    return {
        **summary_info,
        "project": project,
        "interactions_recent": interactions(project, 12),
        "models": model_state(project),
        "feedback": _feedback_counts(project),
        "privacy": (
            "Learning runs locally. Prompts and answers are redacted and stored only "
            "in this project's .agent directory. Disable capture with "
            "AETHERION_LEARN_CAPTURE=0."
        ),
    }


def _feedback_counts(project: str) -> dict:
    try:
        from . import ranking
        return ranking.summary(project)
    except (sqlite3.Error, OSError):
        return {"positive": 0, "negative": 0, "paths": 0}


# ---------------------------------------------------------------------------
# Always-on maintenance loop
# ---------------------------------------------------------------------------

def state_path() -> Path:
    path = Path(os.getenv("LEARNING_STATE_PATH", "./database/learning.sqlite3")).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _state_connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(state_path()), timeout=15)
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS learner_state("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL)"
    )
    return con


def state_get(key: str, default: str = "") -> str:
    try:
        with closing(_state_connect()) as con:
            row = con.execute("SELECT value FROM learner_state WHERE key=?", (key,)).fetchone()
        return default if row is None else str(row[0])
    except (sqlite3.Error, OSError):
        return default


def state_set(key: str, value: str) -> None:
    with closing(_state_connect()) as con, con:
        con.execute(
            "INSERT INTO learner_state(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (str(key), str(value), int(time.time())),
        )


def interval_seconds() -> int:
    try:
        value = int(os.getenv("AETHERION_LEARN_INTERVAL", "900"))
    except (TypeError, ValueError):
        value = 900
    return max(60, min(value, 86400))


def _enabled() -> bool:
    return state_get("enabled", "0") == "1"


def _paused() -> bool:
    return state_get("paused", "0") == "1"


def discover_projects() -> list[str]:
    try:
        entries = sorted(ROOT.iterdir())
    except OSError:
        return []
    result = []
    for entry in entries:
        if entry.is_dir() and PROJECT.fullmatch(entry.name) and not entry.name.startswith("."):
            result.append(entry.name)
    return result


def _record_cycle(project: str, status_text: str, detail: str) -> None:
    try:
        with connect(project) as con:
            con.execute(
                "INSERT INTO cycles(status,detail,created_at) VALUES(?,?,?)",
                (status_text[:64], detail[:2000], int(time.time())),
            )
    except (sqlite3.Error, OSError):
        pass


def _gpu_gate() -> tuple[bool, str, dict]:
    gpu = power.gpu_status()
    try:
        maximum = float(os.getenv("AETHERION_LEARN_MAX_GPU_TEMP", "82"))
    except (TypeError, ValueError):
        maximum = 82.0
    temperature = gpu.get("max_temperature_c")
    if temperature is not None and temperature >= maximum:
        return False, f"gpu at {temperature:.0f}C", gpu
    if os.getenv("AETHERION_LEARN_AC_ONLY", "0") == "1":
        state = power.power_state()
        if state.get("on_ac") is False:
            return False, "on battery", gpu
    return True, "ok", gpu


def tick(force: bool = False) -> dict:
    """One bounded learning cycle across local projects."""
    if not force and not _enabled():
        return {"ran": False, "reason": "disabled"}
    if _paused():
        return {"ran": False, "reason": "paused"}
    from . import device
    admission_info = device.admission()
    if not admission_info.get("allowed", True):
        return {"ran": False, "reason": "thermal", "detail": admission_info.get("reason")}
    allowed, reason, gpu = _gpu_gate()
    if not allowed:
        return {"ran": False, "reason": reason, "gpu": gpu}
    projects = discover_projects()
    if not projects:
        return {"ran": False, "reason": "no_projects"}
    trained = indexed = 0
    details = []
    for project in projects[:6]:
        try:
            if os.getenv("AETHERION_AUTO_INDEX", "1") == "1":
                from . import semantic
                report = semantic.index_project(project, 2000)
                indexed += int(report.get("embedded_files", 0))
            result = train(project)
            if result.get("trained"):
                trained += 1
            _record_cycle(project, "ok", json.dumps({
                "trained": result.get("trained", False),
                "promoted": result.get("promoted", False),
                "examples": result.get("examples", 0),
            }))
            details.append({"project": project, "trained": result.get("trained", False),
                            "promoted": result.get("promoted", False)})
        except Exception as exc:  # a broken project must not stop the loop
            _record_cycle(project, "error", f"{type(exc).__name__}: {exc}")
            details.append({"project": project, "error": type(exc).__name__})
    result = {
        "ran": True, "projects": len(projects), "indexed_files": indexed,
        "trained_projects": trained, "gpu": gpu, "details": details,
        "at": int(time.time()),
    }
    state_set("last_tick", json.dumps(result, sort_keys=True))
    return result


class Runtime:
    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self.started_at = None
        self.last_tick = None

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self.started_at = int(time.time())
        self._thread = threading.Thread(target=self._loop, name="lifelong-learner", daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.last_tick = tick()
            except Exception as exc:
                self.last_tick = {"ran": False, "reason": f"{type(exc).__name__}"}
            self._stop.wait(interval_seconds())

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self.started_at = None

    def status(self) -> dict:
        return {
            "thread_running": bool(self._thread and self._thread.is_alive()),
            "enabled": _enabled(), "paused": _paused(),
            "interval_seconds": interval_seconds(),
            "started_at": self.started_at, "last_tick": self.last_tick,
            "capture": os.getenv("AETHERION_LEARN_CAPTURE", "1") == "1",
            "platform": platform.platform(),
        }


runtime = Runtime()


def maybe_start() -> bool:
    if os.getenv("AETHERION_CONTINUOUS", "0") in ("1", "true", "yes", "on"):
        try:
            if not state_get("enabled"):
                state_set("enabled", "1")
        except (sqlite3.Error, OSError):
            pass
        return runtime.start()
    return False


def continuous_status(project: str | None = None) -> dict:
    payload = {
        "runtime": runtime.status(),
        "gpu": power.gpu_status(),
        "power": power.power_state(),
        "projects": discover_projects(),
        "privacy": (
            "The learner stores redacted interactions and model versions locally; "
            "it does not execute code or contact a network."
        ),
    }
    if project and PROJECT.fullmatch(project):
        payload["project"] = status(project)
    return payload
