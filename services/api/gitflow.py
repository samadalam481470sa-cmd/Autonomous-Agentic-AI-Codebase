"""Git status, branch, commit and pull-request preparation.

Commits are local and explicit: the operator approves a digest-free, path-scoped
staging list and a message. Nothing here force-updates a ref or rewrites history.
Pushing is opt-in: it needs ``GIT_ALLOW_PUSH=1`` in the server environment and an
approval header, and it only ever pushes the current branch to its upstream.
Pull-request preparation assembles a branch name, a body and a compare URL.
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import worktrees
from .engine import workspace
from .studio import authorize

router = APIRouter(prefix="/api/git", tags=["git"])

BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,80}$")
MAX_PATHS = 64
GITHUB = re.compile(r"github\.com[:/](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?$")


def repository(project: str):
    root = workspace(project)
    try:
        return worktrees.repository_root(root)
    except ValueError as error:
        raise HTTPException(400, str(error))


def branch_name(value) -> str:
    name = str(value or "").strip()
    if (not BRANCH.fullmatch(name) or ".." in name or name.startswith("-")
            or name.endswith("/") or name.endswith(".lock")):
        raise ValueError("Invalid branch name")
    return name


def safe_paths(values) -> list[str]:
    from .toolchains import safe_relative
    if not isinstance(values, list) or not values:
        return []
    if len(values) > MAX_PATHS:
        raise ValueError("Too many paths")
    cleaned = []
    for value in values:
        cleaned.append(safe_relative(value))
    return cleaned


def _branch(root) -> str:
    result = worktrees.git(root, "branch", "--show-current")
    return result["stdout"] or "(detached)"


def status(root) -> dict:
    porcelain = worktrees.git(root, "status", "--porcelain")
    stat = worktrees.git(root, "diff", "--stat")
    log = worktrees.git(root, "log", "-5", "--oneline")
    files = [line[2:].strip() for line in porcelain["stdout"].splitlines() if len(line) > 3]
    return {
        "branch": _branch(root),
        "clean": porcelain["stdout"] == "",
        "files": files,
        "diff_stat": stat["stdout"],
        "recent_commits": log["stdout"].splitlines(),
        "repository": str(root),
    }


def create_branch(root, name) -> dict:
    name = branch_name(name)
    existing = worktrees.git(root, "rev-parse", "--verify", "--quiet", "refs/heads/" + name)
    if existing["code"] == 0:
        raise HTTPException(409, "Branch already exists")
    result = worktrees.git(root, "switch", "-c", name)
    if result["code"] != 0:
        result = worktrees.git(root, "checkout", "-b", name)
    if result["code"] != 0:
        raise HTTPException(400, "Could not create branch: " + (result["stderr"] or "git failed"))
    return {"branch": name, "created": True}


def commit(root, message, paths) -> dict:
    message = str(message or "").strip()
    if not 3 <= len(message) <= 2000:
        raise ValueError("Commit message must be 3 to 2000 characters")
    selected = safe_paths(paths)
    if selected:
        staged = worktrees.git(root, "add", "--", *selected)
    else:
        staged = worktrees.git(root, "add", "-u")
    if staged["code"] != 0:
        raise ValueError("Could not stage files: " + (staged["stderr"] or "git failed"))
    pending = worktrees.git(root, "diff", "--cached", "--name-only")
    if not pending["stdout"]:
        raise HTTPException(409, "No staged changes to commit")
    result = worktrees.git(root, "commit", "-m", message)
    if result["code"] != 0:
        raise HTTPException(400, "Commit failed: " + (result["stderr"] or "git failed"))
    head = worktrees.git(root, "rev-parse", "HEAD")
    return {"committed": True, "sha": head["stdout"], "branch": _branch(root),
            "files": pending["stdout"].splitlines(), "output": result["stdout"][:2000]}


def push(root, remote: str = "origin") -> dict:
    """Opt-in, non-force push of the current branch. Never rewrites history."""
    if os.getenv("GIT_ALLOW_PUSH") != "1":
        raise HTTPException(
            503, "Set GIT_ALLOW_PUSH=1 in the server environment to push from the app")
    branch = _branch(root)
    if branch == "(detached)":
        raise HTTPException(409, "Check out a branch before pushing")
    if not _remote_url(root):
        raise HTTPException(400, "No origin remote is configured")
    result = worktrees.git(root, "push", "--set-upstream", remote, branch)
    if result["code"] != 0:
        raise HTTPException(400, "Push failed: " + ((result["stderr"] or "git failed")[:500]))
    return {
        "pushed": True,
        "branch": branch,
        "remote": remote,
        "head": worktrees.git(root, "rev-parse", "HEAD")["stdout"],
        "note": "Create the pull request on your forge from this branch.",
    }


def _remote_url(root) -> str:
    result = worktrees.git(root, "remote", "get-url", "origin")
    return result["stdout"] if result["code"] == 0 else ""


def compare_url(remote: str, base: str, branch: str) -> str:
    match = GITHUB.search(remote or "")
    if not match:
        return ""
    owner, repo = match.group("owner"), match.group("repo")
    return (f"https://github.com/{owner}/{repo}/compare/{base}..."
            f"{branch}?expand=1")


def pull_request(root, title, base) -> dict:
    base = branch_name(base or os.getenv("GIT_BASE_BRANCH", "main"))
    branch = _branch(root)
    if branch in ("(detached)", base):
        raise HTTPException(409, "Switch to a feature branch before preparing a pull request")
    stat = worktrees.git(root, "diff", "--stat", f"{base}...{branch}")
    commits = worktrees.git(root, "log", f"{base}..{branch}", "--oneline")
    remote = _remote_url(root)
    default_title = (commits["stdout"].splitlines()[0].split(" ", 1)[-1]
                     if commits["stdout"] else branch)
    body = "\n".join([
        "## Summary",
        title or default_title,
        "",
        "## Changes",
        stat["stdout"] or "(no committed diff against the base branch)",
        "",
        "## Commits",
        commits["stdout"] or "(none)",
        "",
        "Prepared locally by Autonomous Agentic AI Codebase. Nothing was pushed "
        "and no pull request was created automatically.",
    ]).strip()
    return {
        "branch": branch,
        "base": base,
        "title": str(title or default_title)[:200],
        "body": body[:20_000],
        "compare_url": compare_url(remote, base, branch),
        "pushed": False,
        "note": ("Push with POST /api/git/push when GIT_ALLOW_PUSH=1, or push the "
                 "branch yourself, then open the compare URL."),
    }


class StatusRequest(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class BranchRequest(StatusRequest):
    name: str = Field(min_length=1, max_length=90)


class CommitRequest(StatusRequest):
    message: str = Field(min_length=3, max_length=2000)
    paths: list[str] = Field(default_factory=list, max_length=MAX_PATHS)


class PullRequestRequest(StatusRequest):
    title: str | None = Field(default=None, max_length=200)
    base: str | None = Field(default=None, max_length=90)


@router.post("/status")
def git_status(body: StatusRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    return status(repository(body.project))


@router.post("/branch")
def git_branch(body: BranchRequest, authorization: str | None = Header(default=None),
               x_confirm_change: str | None = Header(default=None)):
    authorize(authorization)
    if x_confirm_change != "approve":
        raise HTTPException(428, "Explicit human approval required")
    try:
        return create_branch(repository(body.project), body.name)
    except ValueError as error:
        raise HTTPException(400, str(error))


@router.post("/commit")
def git_commit(body: CommitRequest, authorization: str | None = Header(default=None),
               x_confirm_change: str | None = Header(default=None)):
    authorize(authorization)
    if x_confirm_change != "approve":
        raise HTTPException(428, "Explicit human approval required")
    try:
        return commit(repository(body.project), body.message, body.paths)
    except ValueError as error:
        raise HTTPException(400, str(error))


@router.post("/push")
def git_push(body: StatusRequest, authorization: str | None = Header(default=None),
             x_confirm_change: str | None = Header(default=None)):
    authorize(authorization)
    if x_confirm_change != "approve":
        raise HTTPException(428, "Explicit human approval required")
    return push(repository(body.project))


@router.post("/pull-request")
def git_pull_request(body: PullRequestRequest,
                     authorization: str | None = Header(default=None)):
    authorize(authorization)
    return pull_request(repository(body.project), body.title, body.base)
