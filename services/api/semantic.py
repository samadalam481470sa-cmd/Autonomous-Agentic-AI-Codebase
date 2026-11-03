"""Local semantic code retrieval and retrieval-augmented context.

Embeddings are computed offline with a deterministic hashed feature model:
code-aware tokenisation (camelCase, snake_case, digit groups), character
4-grams for long identifiers, sublinear term frequency, query-time inverse
document frequency and signed feature hashing into a fixed number of buckets.
No weights are downloaded, nothing leaves the machine, and there is no network
dependency. Vectors are stored sparsely in SQLite next to the incremental FTS5
index, so indexing is bounded and repeat runs only embed changed files.

Retrieval is hybrid: vector cosine similarity fused with SQLite FTS5 BM25 by
reciprocal rank. Entity text returned to a model is always treated as
untrusted repository data, never as instructions.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import sqlite3
import struct
import time
from contextlib import closing
from pathlib import Path

from .engine import safe_path, workspace
from . import code_index, content_safety, ranking

EMBEDDING_MODEL = "local-hashed-tfidf-v1"
DEFAULT_DIMENSIONS = 256
MAX_QUERY_CHARS = 500
MAX_SCAN_VECTORS = 50000
STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "these", "those", "from", "into",
    "return", "def", "class", "import", "from", "const", "let", "var", "function",
    "self", "none", "true", "false", "null", "new", "await", "async", "public",
    "private", "protected", "void", "static", "if", "else", "elif", "then", "while",
    "try", "catch", "except", "finally", "not", "or", "in", "is", "as", "to", "of",
    "a", "an", "be", "it", "on", "by", "at", "we", "you", "they", "can", "will",
    "should", "would", "have", "has", "had", "does", "did", "was", "were", "are",
}


def dimensions() -> int:
    try:
        value = int(os.getenv("SEMANTIC_DIM", str(DEFAULT_DIMENSIONS)))
    except (TypeError, ValueError):
        value = DEFAULT_DIMENSIONS
    return max(32, min(value, 4096))


def min_score() -> float:
    try:
        value = float(os.getenv("SEMANTIC_MIN_SCORE", "0.05"))
    except (TypeError, ValueError):
        value = 0.05
    return max(0.0, min(value, 1.0))


def _bucket(feature: str, dim: int) -> int:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dim


def tokenize(text: str) -> list[str]:
    features: list[str] = []
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*|\d{2,}", text):
        raw = match.group(0)
        pieces = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", raw) or [raw]
        for piece in pieces:
            token = piece.lower()
            if len(token) < 2 or token in STOPWORDS:
                continue
            features.append(token)
            if len(token) >= 6:
                for index in range(min(len(token) - 3, 6)):
                    features.append("~" + token[index:index + 4])
    return features


def embed(text: str, idf: dict[int, float] | None = None,
          default_idf: float = 1.0, dim: int | None = None) -> list[tuple[int, float]]:
    """Signed hashed TF(-IDF) vector, L2 normalised and stored sparsely."""
    size = dim or dimensions()
    counts: dict[int, float] = {}
    for feature in tokenize(text):
        bucket = _bucket(feature, size)
        weight = 0.45 if feature.startswith("~") else 1.0
        counts[bucket] = counts.get(bucket, 0.0) + weight
    weights = {}
    for bucket, count in counts.items():
        weight = 1.0 + math.log(count)
        if idf is not None:
            weight *= idf.get(bucket, default_idf)
        weights[bucket] = weight
    norm = math.sqrt(sum(value * value for value in weights.values()))
    if norm == 0:
        return []
    return sorted((bucket, weight / norm) for bucket, weight in weights.items())


def pack(vector: list[tuple[int, float]]) -> bytes:
    return b"".join(struct.pack("<Hf", bucket, weight) for bucket, weight in vector)


def unpack(blob: bytes) -> list[tuple[int, float]]:
    usable = len(blob) - (len(blob) % struct.calcsize("<Hf"))
    return [(bucket, weight) for bucket, weight in struct.iter_unpack("<Hf", blob[:usable])]


def dot(query: dict[int, float], document: list[tuple[int, float]]) -> float:
    return sum(query.get(bucket, 0.0) * weight for bucket, weight in document)


def _db(project: str) -> sqlite3.Connection:
    path = workspace(project) / ".agent" / "semantic.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS sem_files(
          path TEXT PRIMARY KEY, hash TEXT NOT NULL, chunks INTEGER NOT NULL,
          updated_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sem_vectors(
          path TEXT NOT NULL, line INTEGER NOT NULL, body TEXT NOT NULL,
          vec BLOB NOT NULL, dim INTEGER NOT NULL, PRIMARY KEY(path,line));
        CREATE TABLE IF NOT EXISTS sem_df(bucket INTEGER PRIMARY KEY, count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sem_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    return con


def _meta_get(con, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM sem_meta WHERE key=?", (key,)).fetchone()
    return default if row is None else str(row["value"])


def _read_text(item: Path) -> str | None:
    try:
        if item.stat().st_size > code_index.MAX_FILE_BYTES:
            return None
        data = item.read_bytes()
        if b"\x00" in data:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeError):
        return None


def index_project(project: str, max_files: int = 10000) -> dict:
    """Incrementally embed changed files. Reuses the bounded source walker."""
    lexical = code_index.index_project(project, max_files)
    root = workspace(project)
    seen: set[str] = set()
    embedded = 0
    unchanged = 0
    skipped = 0
    removed = 0
    truncated = False
    total_vectors = 0
    size = dimensions()
    started = time.time()

    with closing(_db(project)) as con:
        with con:
            for item in code_index.sources(root):
                if len(seen) >= max_files:
                    truncated = True
                    break
                relative = item.relative_to(root).as_posix()
                seen.add(relative)
                text = _read_text(item)
                if text is None:
                    skipped += 1
                    con.execute("DELETE FROM sem_vectors WHERE path=?", (relative,))
                    con.execute("DELETE FROM sem_files WHERE path=?", (relative,))
                    continue
                checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
                row = con.execute("SELECT hash FROM sem_files WHERE path=?", (relative,)).fetchone()
                if row is not None and row["hash"] == checksum:
                    unchanged += 1
                    continue
                lines = text.splitlines()
                rows = []
                for start in range(0, len(lines), code_index.CHUNK_LINES):
                    body = "\n".join(lines[start:start + code_index.CHUNK_LINES])
                    vector = embed(body, dim=size)
                    if not vector:
                        continue
                    rows.append((relative, start + 1, body, pack(vector), size))
                con.execute("DELETE FROM sem_vectors WHERE path=?", (relative,))
                if rows:
                    con.executemany(
                        "INSERT INTO sem_vectors(path,line,body,vec,dim) VALUES(?,?,?,?,?)", rows
                    )
                con.execute(
                    "INSERT INTO sem_files(path,hash,chunks,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET hash=excluded.hash,"
                    "chunks=excluded.chunks,updated_at=excluded.updated_at",
                    (relative, checksum, len(rows), int(time.time())),
                )
                embedded += 1

            if not truncated:
                for row in con.execute("SELECT path FROM sem_files").fetchall():
                    if row["path"] not in seen:
                        con.execute("DELETE FROM sem_vectors WHERE path=?", (row["path"],))
                        con.execute("DELETE FROM sem_files WHERE path=?", (row["path"],))
                        removed += 1

            con.execute("DELETE FROM sem_df")
            df: dict[int, int] = {}
            for row in con.execute("SELECT vec FROM sem_vectors"):
                for bucket, _ in unpack(row["vec"]):
                    df[bucket] = df.get(bucket, 0) + 1
            con.executemany(
                "INSERT INTO sem_df(bucket,count) VALUES(?,?)",
                [(bucket, count) for bucket, count in df.items()],
            )
            total_vectors = con.execute("SELECT COUNT(*) FROM sem_vectors").fetchone()[0]
            for key, value in (
                ("model", EMBEDDING_MODEL), ("dim", str(size)),
                ("indexed_at", str(int(time.time()))), ("files", str(len(seen))),
                ("vectors", str(total_vectors)),
            ):
                con.execute(
                    "INSERT INTO sem_meta(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
                )

    return {
        "model": EMBEDDING_MODEL,
        "dimensions": size,
        "embedded_files": embedded,
        "unchanged_files": unchanged,
        "skipped_files": skipped,
        "removed_files": removed,
        "truncated": truncated,
        "vectors": total_vectors,
        "elapsed_seconds": round(time.time() - started, 3),
        "lexical": lexical,
    }


def _query_vector(con, query: str) -> dict[int, float]:
    """Query-time IDF downweights ubiquitous identifiers without re-embedding docs."""
    total = con.execute("SELECT COUNT(*) FROM sem_vectors").fetchone()[0]
    df = {row["bucket"]: row["count"] for row in con.execute("SELECT bucket,count FROM sem_df")}
    idf = {bucket: math.log((total + 1) / (count + 1)) + 1.0 for bucket, count in df.items()}
    default_idf = math.log(total + 1) + 1.0 if total else 1.0
    return dict(embed(query[:MAX_QUERY_CHARS], idf=idf, default_idf=default_idf))


def _excerpt(body: str, query: str, limit: int = 360) -> tuple[str, int]:
    lines = body.splitlines() or [""]
    needles = [token for token in tokenize(query) if not token.startswith("~")][:8]
    start = 0
    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(needle in lowered for needle in needles):
            start = index
            break
    return "\n".join(lines[start:start + 6]).strip()[:limit], start


def semantic_scores(project: str, query: str, limit: int = 50) -> list[dict]:
    with closing(_db(project)) as con:
        vector = _query_vector(con, query)
        if not vector:
            return []
        rows = con.execute(
            "SELECT path,line,body,vec FROM sem_vectors LIMIT ?", (MAX_SCAN_VECTORS,)
        ).fetchall()
    scored = []
    threshold = min_score()
    for row in rows:
        score = dot(vector, unpack(row["vec"]))
        if score <= threshold:
            continue
        scored.append({"score": score, "path": row["path"], "line": int(row["line"]),
                       "body": row["body"]})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:max(1, limit)]


def search(project: str, query: str, limit: int = 10, mode: str = "hybrid") -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    if mode not in ("hybrid", "semantic", "lexical"):
        raise ValueError("mode must be hybrid, semantic or lexical")
    limit = max(1, min(int(limit), 50))
    semantic = semantic_scores(project, query, limit * 5) if mode in ("hybrid", "semantic") else []
    lexical = code_index.search_project(project, query, max(limit, 10)) if mode in ("hybrid", "lexical") else []

    fused: dict[tuple[str, int], dict] = {}
    for rank, item in enumerate(semantic):
        excerpt, offset = _excerpt(item["body"], query)
        key = (item["path"], item["line"])
        fused[key] = {
            "path": item["path"], "line": item["line"] + offset, "excerpt": excerpt,
            "semantic_score": round(item["score"], 5), "lexical_score": None,
            "score": 1.0 / (60 + rank + 1), "sources": ["semantic"],
        }
    for rank, item in enumerate(lexical):
        key = (item["path"], item["line"])
        contribution = 1.0 / (60 + rank + 1)
        if key in fused:
            fused[key]["lexical_score"] = item["score"]
            fused[key]["score"] += contribution
            fused[key]["sources"].append("lexical")
        else:
            fused[key] = {
                "path": item["path"], "line": item["line"], "excerpt": item["excerpt"],
                "semantic_score": None, "lexical_score": item["score"],
                "score": contribution, "sources": ["lexical"],
            }
    results = sorted(fused.values(), key=lambda item: item["score"], reverse=True)
    for item in results:
        item["score"] = round(item["score"], 6)
        item["sources"] = sorted(set(item["sources"]))
    results = _apply_feedback(project, results)
    return results[:limit]


def _apply_feedback(project: str, results: list[dict]) -> list[dict]:
    """Add the learned per-path bonus/penalty and re-sort."""
    strength = ranking.weight()
    if not results or strength <= 0:
        return results
    try:
        boosts = ranking.boost_map(project)
    except (sqlite3.Error, OSError):
        return results
    for item in results:
        learned = round(strength * boosts.get(item["path"], 0.0), 6)
        item["learned_boost"] = learned
        item["score"] = round(item["score"] + learned, 6)
    return sorted(results, key=lambda item: item["score"], reverse=True)


def context(project: str, query: str, budget_chars: int = 6000,
            max_files: int = 6) -> dict:
    """Budgeted, deduplicated excerpts for a model prompt."""
    budget = max(200, min(int(budget_chars), 24000))
    max_files = max(1, min(int(max_files), 20))
    try:
        results = search(project, query, limit=max(12, max_files * 4), mode="hybrid")
    except (sqlite3.Error, OSError, ValueError):
        return {"text": "", "citations": [], "used_chars": 0,
                "safety": {"secrets": 0, "injection": 0, "risk": "none"}}
    blocks: list[str] = []
    citations: list[dict] = []
    used = 0
    redactions = 0
    injection_flags = 0
    per_file: dict[str, int] = {}
    for item in results:
        if per_file.get(item["path"], 0) >= 2:
            continue
        if item["path"] in per_file and len(per_file) >= max_files:
            continue
        safe = content_safety.scan_and_redact(item["excerpt"].strip())
        block = f"[{item['path']}:{item['line']}]\n{safe['text']}\n"
        if used + len(block) > budget:
            break
        blocks.append(block)
        used += len(block)
        per_file[item["path"]] = per_file.get(item["path"], 0) + 1
        redactions += safe["safety"]["secrets"]
        injection_flags += safe["safety"]["injection"]
        citations.append({"path": item["path"], "line": item["line"],
                          "score": item["score"], "sources": item["sources"],
                          "redactions": safe["safety"]["secrets"],
                          "injection_risk": safe["safety"]["risk"]})
        if len(per_file) >= max_files:
            break
    text = ""
    if blocks:
        text = ("<untrusted_repository_context>\n"
                + "\n".join(blocks)
                + "</untrusted_repository_context>")
    risk = "high" if redactions else ("medium" if injection_flags else "none")
    return {"text": text, "citations": citations, "used_chars": used,
            "safety": {"secrets": redactions, "injection": injection_flags,
                       "risk": risk}}


def file_vector(con, relative: str) -> dict[int, float]:
    total: dict[int, float] = {}
    rows = con.execute("SELECT vec FROM sem_vectors WHERE path=?", (relative,)).fetchall()
    for row in rows:
        for bucket, weight in unpack(row["vec"]):
            total[bucket] = total.get(bucket, 0.0) + weight
    norm = math.sqrt(sum(value * value for value in total.values()))
    return {} if norm == 0 else {bucket: value / norm for bucket, value in total.items()}


def similar(project: str, path: str, limit: int = 8) -> list[dict]:
    target = safe_path(project, path)
    root = workspace(project)
    relative = target.relative_to(root).as_posix()
    with closing(_db(project)) as con:
        vector = file_vector(con, relative)
        if not vector:
            raise ValueError("File is not indexed; index the project first")
        best: dict[str, dict] = {}
        for row in con.execute("SELECT path,line,body,vec FROM sem_vectors LIMIT ?",
                              (MAX_SCAN_VECTORS,)).fetchall():
            if row["path"] == relative:
                continue
            score = dot(vector, unpack(row["vec"]))
            current = best.get(row["path"])
            if current is None or score > current["score"]:
                best[row["path"]] = {"path": row["path"], "line": int(row["line"]),
                                     "score": score, "body": row["body"]}
    ranked = sorted(best.values(), key=lambda item: item["score"], reverse=True)
    results = []
    for item in ranked[:max(1, min(int(limit), 20))]:
        excerpt, offset = _excerpt(item["body"], path)
        results.append({"path": item["path"], "line": item["line"] + offset,
                        "excerpt": excerpt, "score": round(item["score"], 5)})
    return results


def stats(project: str) -> dict:
    with closing(_db(project)) as con:
        files = con.execute("SELECT COUNT(*) FROM sem_files").fetchone()[0]
        vectors = con.execute("SELECT COUNT(*) FROM sem_vectors").fetchone()[0]
        terms = con.execute("SELECT COUNT(*) FROM sem_df").fetchone()[0]
        meta = {row["key"]: row["value"] for row in con.execute("SELECT key,value FROM sem_meta")}
    return {
        "model": meta.get("model", EMBEDDING_MODEL),
        "dimensions": int(meta.get("dim", str(dimensions()))),
        "indexed_files": files,
        "vectors": vectors,
        "df_terms": terms,
        "last_indexed_at": int(meta["indexed_at"]) if meta.get("indexed_at") else None,
        "backend": "numpy" if _numpy_available() else "pure-python",
        "feedback": ranking.summary(project),
        "safety_screening": "secrets + prompt-injection redaction",
    }


def _numpy_available() -> bool:
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True
