"""Git worktree per agent run.

A worktree isolates file changes and branch state. It is **not** a security
boundary: generated code still runs on the host unless a sandbox is used. All
git calls are argv-only and paths are confined to the configured worktree root.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
DEFAULT_IGNORE = {".git", ".agent", "node_modules", ".venv", "target", "dist", "build"}


def git(root, *args, timeout=60) -> dict:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        timeout=timeout, check=False, encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return {"code": result.returncode, "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()}


def repository_root(project_root) -> Path:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError("Project directory does not exist")
    result = git(root, "rev-parse", "--show-toplevel")
    if result["code"] != 0:
        raise ValueError("Project is not a git repository")
    found = Path(result["stdout"]).resolve()
    if found != root and not found.is_relative_to(root) and not root.is_relative_to(found):
        raise ValueError("Project is not inside its git repository")
    return found


def worktrees_root(project_root, override=None) -> Path:
    root = Path(project_root).resolve()
    if override:
        destination = Path(override).expanduser().resolve()
    elif os.getenv("WORKTREES_ROOT"):
        destination = Path(os.environ["WORKTREES_ROOT"]).expanduser().resolve()
    else:
        destination = Path.home() / ".agentic-ai" / "worktrees" / root.name
    if destination == root or root.is_relative_to(destination):
        raise ValueError("Worktree root must not contain the project checkout")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def create(project_root, run_id, *, base="HEAD", override=None) -> dict:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run id")
    root = repository_root(project_root)
    destination = worktrees_root(root, override)
    target = (destination / run_id).resolve()
    if not target.is_relative_to(destination):
        raise ValueError("Worktree escapes the configured root")
    if target.exists():
        raise ValueError("Worktree already exists for this run")
    branch = f"agentic/run-{run_id[:12]}"
    existing = git(root, "rev-parse", "--verify", "--quiet", branch)
    if existing["code"] == 0:
        branch = f"{branch}-{run_id[12:20]}"
    result = git(root, "worktree", "add", "-b", branch, str(target), base)
    if result["code"] != 0:
        raise ValueError("Unable to create worktree: " + (result["stderr"] or "git failed"))
    return {
        "run_id": run_id, "path": str(target), "branch": branch,
        "base": base, "project_root": str(root),
    }


def list_worktrees(project_root, override=None) -> list[dict]:
    root = repository_root(project_root)
    destination = worktrees_root(root, override)
    result = git(root, "worktree", "list", "--porcelain")
    if result["code"] != 0:
        return []
    entries = []
    for chunk in result["stdout"].split("\n\n"):
        record = {}
        for line in chunk.splitlines():
            key, _, value = line.partition(" ")
            if key:
                record[key] = value
        location = record.get("worktree")
        if not location:
            continue
        path = Path(location).resolve()
        if path.is_relative_to(destination):
            record["path"] = location
            record["run_id"] = path.name
            entries.append(record)
    return entries


def remove(project_root, path, *, override=None, force=True) -> dict:
    root = repository_root(project_root)
    destination = worktrees_root(root, override)
    target = Path(path).resolve()
    if not target.is_relative_to(destination):
        raise ValueError("Refusing to remove a worktree outside the configured root")
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(target))
    result = git(root, *args)
    if result["code"] != 0:
        raise ValueError("Unable to remove worktree: " + (result["stderr"] or "git failed"))
    git(root, "worktree", "prune")
    return {"removed": True, "path": str(target)}


def changes(path) -> dict:
    directory = Path(path).resolve()
    if not directory.is_dir():
        raise ValueError("Worktree does not exist")
    status = git(directory, "status", "--porcelain")
    diff = git(directory, "diff", "--stat")
    # Porcelain lines are "XY path"; the first line may have lost its leading
    # space when git output was trimmed, so skip the two status columns.
    names = [line[2:].strip() for line in status["stdout"].splitlines() if len(line) > 3]
    return {
        "path": str(directory),
        "clean": status["stdout"] == "",
        "files": names,
        "stat": diff["stdout"],
    }
