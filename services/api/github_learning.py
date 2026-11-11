"""Import public GitHub repositories as local, indexed learning projects.

This is retrieval learning, not model-weight training. A repository is fetched
only from fixed GitHub hosts, unpacked with strict path/size limits, stored as a
new project, and indexed by the existing local FTS5 + semantic pipeline. The
source remains attributed by repository, branch, commit and detected license.

The feature is deliberately disabled unless ``GITHUB_LEARNING=1``. It uses no
GitHub token by default; set ``GITHUB_TOKEN`` only if you need a higher rate
limit, and it is sent server-side and never returned to the browser.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path, PurePosixPath

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import code_index, engine, semantic
from .studio import authorize

router = APIRouter(prefix="/api/github", tags=["github-learning"])

API_ROOT = "https://api.github.com"
ARCHIVE_ROOT = "https://codeload.github.com"
MAX_ARCHIVE_BYTES = 24 * 1024 * 1024
MAX_EXTRACTED_BYTES = 64 * 1024 * 1024
MAX_FILES = 3000
MAX_FILE_BYTES = 1_000_000
PROJECT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
ALLOWED_SUFFIXES = set(code_index.EXTENSIONS) | {
    ".md", ".txt", ".rst", ".toml", ".ini", ".cfg", ".license",
}
ALLOWED_NAMES = {"license", "licence", "copying", "notice"}


class LearnRequest(BaseModel):
    repo: str = Field(min_length=3, max_length=180)
    branch: str | None = Field(default=None, max_length=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=8, ge=1, le=30)


def enabled() -> bool:
    return os.getenv("GITHUB_LEARNING", "0") == "1"


def _db_path() -> Path:
    path = Path(os.getenv("GITHUB_DB_PATH", "./database/github_sources.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _connect():
    con = sqlite3.connect(_db_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS github_sources(
          id TEXT PRIMARY KEY, repo TEXT NOT NULL, branch TEXT NOT NULL,
          commit_sha TEXT NOT NULL, license TEXT NOT NULL DEFAULT 'unknown',
          project TEXT NOT NULL, files INTEGER NOT NULL, bytes INTEGER NOT NULL,
          created_at INTEGER NOT NULL, url TEXT NOT NULL);
        """
    )
    return con


def _client() -> httpx.Client:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Aetherion-OmniForge/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return httpx.Client(timeout=45, follow_redirects=False, trust_env=False,
                        headers=headers)


def _normalise_repo(value: str) -> tuple[str, str]:
    raw = (value or "").strip()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
            break
    raw = raw.strip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    if raw.count("/") != 1:
        raise ValueError("Use owner/repository, for example torvalds/linux")
    owner, repo = raw.split("/", 1)
    if not OWNER_RE.fullmatch(owner) or not REPO_RE.fullmatch(repo):
        raise ValueError("Invalid GitHub owner or repository name")
    if owner in {".", ".."} or repo in {".", ".."} or ".." in repo:
        raise ValueError("Invalid GitHub repository path")
    return owner, repo


def _normalise_branch(value: str | None) -> str | None:
    branch = (value or "").strip()
    if not branch:
        return None
    if (not BRANCH_RE.fullmatch(branch) or branch.startswith("/")
            or branch.endswith("/") or ".." in branch.split("/")):
        raise ValueError("Invalid branch name")
    return branch


def _fetch_metadata(owner: str, repo: str) -> dict:
    try:
        with _client() as client:
            response = client.get(f"{API_ROOT}/repos/{owner}/{repo}")
    except httpx.HTTPError as error:
        raise HTTPException(502, f"GitHub metadata request failed: {type(error).__name__}")
    if response.status_code == 404:
        raise HTTPException(404, "GitHub repository not found")
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        raise HTTPException(429, "GitHub API rate limit reached; set GITHUB_TOKEN or retry later")
    if response.status_code != 200:
        raise HTTPException(502, f"GitHub metadata request returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(502, "GitHub returned invalid metadata")
    if not isinstance(payload, dict):
        raise HTTPException(502, "GitHub returned invalid metadata")
    return payload


def _archive_for(owner: str, repo: str, branch: str) -> bytes:
    from urllib.parse import quote

    url = f"{ARCHIVE_ROOT}/{owner}/{repo}/tar.gz/{quote(branch, safe='/')}"
    try:
        with _client() as client:
            response = client.get(url)
    except httpx.HTTPError as error:
        raise HTTPException(502, f"GitHub archive request failed: {type(error).__name__}")
    if response.status_code != 200:
        raise HTTPException(502, f"GitHub archive request returned HTTP {response.status_code}")
    if len(response.content) > MAX_ARCHIVE_BYTES:
        raise HTTPException(413, f"Repository archive exceeds {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB")
    return response.content


def _allowed_path(relative: str) -> bool:
    name = Path(relative).name.lower()
    if name in ALLOWED_NAMES:
        return True
    return Path(relative).suffix.lower() in ALLOWED_SUFFIXES


def _extract_files(archive: bytes) -> tuple[dict[str, str], str]:
    """Return safe text files and the archive's commit-shaped root name."""
    files: dict[str, str] = {}
    root_name = ""
    total = 0
    seen = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            for member in bundle:
                if member.isdir():
                    if not root_name:
                        root_name = member.name.strip("/").split("/", 1)[0]
                    continue
                if not member.isfile():
                    continue
                seen += 1
                if seen > MAX_FILES:
                    raise ValueError(f"Repository has more than {MAX_FILES} files")
                if member.size < 0 or member.size > MAX_FILE_BYTES:
                    continue
                total += member.size
                if total > MAX_EXTRACTED_BYTES:
                    raise ValueError("Repository expands beyond the safe size limit")
                name = member.name.replace("\\", "/")
                if name.startswith("/") or "\x00" in name:
                    raise ValueError("Repository contains an unsafe path")
                parts = PurePosixPath(name).parts
                if ".." in parts:
                    raise ValueError("Repository contains a path traversal")
                if not parts:
                    continue
                if not root_name:
                    root_name = parts[0]
                relative_parts = parts[1:]
                if not relative_parts:
                    continue
                relative = "/".join(relative_parts)
                if any(part in code_index.SKIP for part in relative_parts):
                    continue
                if any(part.startswith(".") and part not in {".github"} for part in relative_parts):
                    continue
                if not _allowed_path(relative):
                    continue
                handle = bundle.extractfile(member)
                if handle is None:
                    continue
                data = handle.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if "\x00" in text:
                    continue
                files[relative] = text
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ValueError(f"Invalid GitHub archive: {type(error).__name__}")
    if not files:
        raise ValueError("Repository contains no indexable source files")
    return files, root_name


def _project_name(owner: str, repo: str, commit: str) -> str:
    digest = hashlib.sha256(f"{owner}/{repo}@{commit}".encode("utf-8")).hexdigest()[:8]
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", f"gh_{owner}_{repo}_{digest}")
    base = base[:64].strip("_") or "gh_learned"
    candidate = base
    counter = 2
    while (engine.ROOT / candidate).exists():
        suffix = f"_{counter}"
        candidate = base[:64 - len(suffix)] + suffix
        counter += 1
    return candidate


def _source_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "repo": row["repo"], "branch": row["branch"],
        "commit": row["commit_sha"], "license": row["license"],
        "project": row["project"], "files": row["files"], "bytes": row["bytes"],
        "created_at": row["created_at"], "url": row["url"],
    }


def list_sources(limit: int = 30) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    with closing(_connect()) as con:
        rows = con.execute(
            "SELECT * FROM github_sources ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_source_dict(row) for row in rows]


def learn(repo_value: str, branch_value: str | None = None) -> dict:
    if not enabled():
        raise HTTPException(
            503,
            "GitHub learning is disabled. Set GITHUB_LEARNING=1 to allow "
            "public-repository downloads; no code is uploaded.",
        )
    try:
        owner, repo = _normalise_repo(repo_value)
        branch = _normalise_branch(branch_value)
    except ValueError as error:
        raise HTTPException(400, str(error))
    metadata: dict = {}
    try:
        metadata = _fetch_metadata(owner, repo)
    except HTTPException as error:
        # The unauthenticated API is commonly rate-limited on shared networks.
        # codeload does not require that API, so probe the conventional branches
        # while keeping the reduced metadata visible as "unknown".
        if error.status_code == 404:
            raise
    default_branch = metadata.get("default_branch") or "main"
    branch = branch or str(default_branch)
    if not _normalise_branch(branch):
        raise HTTPException(400, "GitHub returned an invalid default branch")
    candidates = [branch]
    if not branch_value:
        for candidate in ("main", "master"):
            if candidate not in candidates:
                candidates.append(candidate)
    archive = None
    archive_error: HTTPException | None = None
    for candidate in candidates:
        try:
            archive = _archive_for(owner, repo, candidate)
            branch = candidate
            break
        except HTTPException as error:
            archive_error = error
            if error.status_code == 404:
                continue
            if not branch_value:
                continue
            raise
    if archive is None:
        raise archive_error or HTTPException(502, "GitHub archive unavailable")
    try:
        files, archive_root = _extract_files(archive)
    except ValueError as error:
        raise HTTPException(400, str(error))
    commit = archive_root.rsplit("-", 1)[-1][:40]
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        commit = hashlib.sha256(archive).hexdigest()[:12]
    project = _project_name(owner, repo, commit)
    root = engine.ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / project).resolve()
    if target.parent != root:
        raise HTTPException(400, "Invalid project path")
    staging = Path(tempfile.mkdtemp(prefix=".github-learning-", dir=str(root)))
    try:
        for relative, text in files.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        metadata_path = staging / ".agent"
        metadata_path.mkdir(parents=True, exist_ok=True)
        (metadata_path / "github-source.json").write_text(
            json.dumps({
                "repo": f"{owner}/{repo}", "branch": branch, "commit": commit,
                "license": (metadata.get("license") or {}).get("spdx_id") or "unknown",
                "url": f"https://github.com/{owner}/{repo}",
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            raise HTTPException(409, "Generated learning project already exists")
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    try:
        index = semantic.index_project(project, max_files=min(MAX_FILES, 5000))
    except Exception as error:
        index = {"error": f"{type(error).__name__}: {error}"}
    license_id = (metadata.get("license") or {}).get("spdx_id") or "unknown"
    source = {
        "id": uuid.uuid4().hex,
        "repo": f"{owner}/{repo}",
        "branch": branch,
        "commit": commit,
        "license": license_id,
        "project": project,
        "files": len(files),
        "bytes": sum(len(value.encode("utf-8")) for value in files.values()),
        "created_at": int(time.time()),
        "url": f"https://github.com/{owner}/{repo}",
    }
    with closing(_connect()) as con, con:
        con.execute(
            "INSERT INTO github_sources(id,repo,branch,commit_sha,license,project,"
            "files,bytes,created_at,url) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (source["id"], source["repo"], source["branch"], source["commit"],
             source["license"], source["project"], source["files"],
             source["bytes"], source["created_at"], source["url"]),
        )
    return {"source": source, "index": index}


def _require_enabled():
    if not enabled():
        raise HTTPException(
            503,
            "GitHub learning is disabled. Set GITHUB_LEARNING=1 to allow "
            "public-repository downloads; no code is uploaded.",
        )


@router.get("/sources")
def sources(limit: int = 30, authorization: str | None = Header(default=None)):
    authorize(authorization)
    return {"sources": list_sources(limit), "enabled": enabled()}


@router.post("/learn")
def learn_endpoint(body: LearnRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    return learn(body.repo, body.branch)


@router.post("/search")
def search_endpoint(body: SearchRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    _require_enabled()
    results: list[dict] = []
    for source in list_sources(50):
        try:
            matches = semantic.search(source["project"], body.query, limit=body.limit)
        except Exception:
            continue
        for match in matches:
            results.append({**match, "repo": source["repo"], "project": source["project"],
                            "license": source["license"]})
    results.sort(key=lambda item: item.get("score", 0), reverse=True)
    return {"query": body.query, "results": results[:body.limit]}
