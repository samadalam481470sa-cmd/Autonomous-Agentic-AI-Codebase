"""Autonomous polyglot coding: detect, scaffold, execute and iterate.

This module lets the agent work in any language the owner's machine can build or
interpret. It discovers the project's languages, plans argv-only toolchain
commands, generates a starter project in any supported language, runs real
checks, and drives a bounded generate -> verify -> retry loop that writes to a
disposable trial directory first. Applying the result to live files is
checkpointed and, by default, requires explicit approval; the desktop build
sets AGENT_AUTONOMY=1 so the loop can finish on its own.

Host toolchain execution is opt-in with AGENT_HOST_TOOLCHAIN=1 because the
commands build and run code on the owner's computer.
"""
from __future__ import annotations

import asyncio
import difflib
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import toolchains
from .code_agent import config as model_config, strip_fence
from .engine import workspace
from .multi_file_agent import apply_record, create_record
from .studio import (WRITE_LOCK, atomic_text_write, authorize, current, digest,
                     resolve)

router = APIRouter(prefix="/api/polyglot", tags=["polyglot"])
MAX_SOURCE_BYTES = 120_000
TRIAL_RUN_TIMEOUT = 30


def autonomy() -> bool:
    return os.getenv("AGENT_AUTONOMY") == "1"


def host_toolchain() -> bool:
    return os.getenv("AGENT_HOST_TOOLCHAIN") == "1"


def require_host_toolchain():
    if not host_toolchain():
        raise HTTPException(
            503,
            "Building or running local code requires AGENT_HOST_TOOLCHAIN=1. "
            "This is enabled by the desktop app; enabling it runs the installed "
            "compilers and interpreters on this computer.",
        )


def require_approval(value, what):
    if autonomy() or value == "approve":
        return
    raise HTTPException(428, f"Explicit human approval required for {what}")


def _language(language) -> str:
    try:
        return toolchains.normalize(str(language))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _capability(language) -> dict:
    try:
        return toolchains.capability(language)
    except KeyError as exc:
        raise HTTPException(400, str(exc).strip("'\""))


def extract_source(text: str) -> str:
    """Accept a bare file or a single fenced block; never invent content."""
    value = strip_fence(str(text or ""))
    if value != str(text or "").strip():
        return value.strip() + "\n"
    match = re.search(r"```[A-Za-z0-9_+#.\-]*\s*\n(.*?)\n```", str(text or ""), flags=re.S)
    if match:
        return match.group(1).strip() + "\n"
    return str(text or "").strip() + "\n"


def verify(language, root, relative, *, verify_run=True, timeout=None) -> dict:
    """Run the toolchain's check/build/test, then (optionally) the program."""
    root = Path(root)
    result = {"check": None, "run": None, "passed": False, "note": ""}
    executed = False
    try:
        check = toolchains.execute(language, "check", root, target=relative, timeout=timeout)
    except ValueError:
        check = None
    if check is None:
        for project_action in ("build", "test"):
            try:
                check = toolchains.execute(language, project_action, root, target=relative,
                                           timeout=timeout)
                break
            except ValueError:
                continue
    if check is not None:
        result["check"] = {**check, "action_name": "check"}
        executed = True
    passed = bool(check and check.get("passed"))
    if passed and verify_run:
        try:
            run = toolchains.execute(language, "run", root, target=relative,
                                     timeout=TRIAL_RUN_TIMEOUT)
        except ValueError:
            run = None
        if run is not None:
            result["run"] = run
            executed = True
            passed = bool(run.get("passed"))
    if not executed:
        result["note"] = "No check, build, test or run command is available for this language"
        passed = False
    result["passed"] = bool(passed and executed)
    return result


def _write_scaffold(project, directory, files, overwrite) -> dict:
    prefix = "" if directory in ("", ".", "./") else toolchains.safe_relative(directory).rstrip("/") + "/"
    created, skipped = [], []
    with WRITE_LOCK:
        for name, content in files.items():
            relative = prefix + name
            target = resolve(project, relative)
            existed = target.is_file()
            previous = current(target) if existed else ""
            if existed and previous == content:
                skipped.append({"path": relative, "reason": "already identical"})
                continue
            if existed and not overwrite:
                skipped.append({"path": relative, "reason": "exists; pass overwrite=true"})
                continue
            from . import checkpoints
            checkpoint = checkpoints.snapshot(project, relative, previous, existed, content)
            atomic_text_write(target, content)
            created.append({"path": relative, "sha256": digest(content),
                            "checkpoint_id": checkpoint, "existed_before": existed})
    return {"created": created, "skipped": skipped}


class ProjectRequest(BaseModel):
    project: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class DetectRequest(ProjectRequest):
    pass


class ScaffoldRequest(ProjectRequest):
    language: str = Field(min_length=1, max_length=64)
    directory: str = Field(default=".", max_length=200)
    verify: bool = True
    overwrite: bool = False


class RunRequest(ProjectRequest):
    language: str = Field(min_length=1, max_length=64)
    action: str = Field(default="check", pattern=r"^(check|run|test|build)$")
    path: str | None = Field(default=None, max_length=400)
    timeout: int = Field(default=120, ge=5, le=900)


class SolveRequest(ProjectRequest):
    instruction: str = Field(min_length=5, max_length=4000)
    language: str = Field(default="auto", max_length=64)
    path: str | None = Field(default=None, max_length=400)
    attempts: int = Field(default=2, ge=1, le=3)
    verify_run: bool = True
    apply: bool | None = None
    queue: bool = False
    priority: int = Field(default=100, ge=0, le=1000)


@router.get("/languages")
def languages(authorization: str | None = Header(default=None)):
    authorize(authorization)
    report = toolchains.report()
    report["host_toolchain_enabled"] = host_toolchain()
    report["autonomy_enabled"] = autonomy()
    return report


@router.post("/detect")
def detect(body: DetectRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    root = workspace(body.project)
    breakdown = toolchains.project_languages(root)
    enriched = []
    for item in breakdown["languages"]:
        info = _capability(item["language"])
        enriched.append({**item, "installed": info["installed"],
                         "executable": info["executable"],
                         "version": info["version"],
                         "actions": info["actions"],
                         "install_hint": info["install_hint"],
                         "recommended": {
                             "check": (item["samples"][0] if item["samples"] else None),
                             "command": (
                                 "check" if "check" in info["actions"] else
                                 "build" if "build" in info["actions"] else
                                 "test" if "test" in info["actions"] else None
                             ),
                         }})
    missing = [{"language": item["language"], "install_hint": item["install_hint"]}
               for item in enriched if not item["installed"]]
    return {
        "project": body.project, "files_scanned": breakdown["files_scanned"],
        "total_coded_files": breakdown["total_coded_files"],
        "languages": enriched, "missing_toolchains": missing,
        "host_toolchain_enabled": host_toolchain(),
    }


@router.post("/register")
def register(body: dict, authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        defined = toolchains.register_custom(body, overwrite=bool(body.get("overwrite")))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, str(exc).strip("'\""))
    info = _capability(defined["name"])
    return {"registered": info, "persisted": str(toolchains.custom_path())}


@router.post("/scaffold")
def scaffold(body: ScaffoldRequest, authorization: str | None = Header(default=None),
             x_confirm_change: str | None = Header(default=None)):
    authorize(authorization)
    require_approval(x_confirm_change, "scaffolding files")
    language = _language(body.language)
    try:
        files = toolchains.scaffold(language)
        directory = toolchains.safe_relative(body.directory) if body.directory not in ("", ".") else "."
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc).strip("'\""))
    written = _write_scaffold(body.project, directory, files, body.overwrite)
    source = next((item["path"] for item in written["created"]), None)
    verification = None
    info = _capability(language)
    if body.verify and source and info["installed"] and host_toolchain():
        verification = verify(language, workspace(body.project), source)
    return {
        "language": language, "toolchain": info,
        "files": written["created"], "skipped": written["skipped"],
        "verification": verification,
        "verified": bool(verification and verification["passed"]),
        "host_toolchain_enabled": host_toolchain(),
    }


@router.post("/run")
def run_toolchain(body: RunRequest, authorization: str | None = Header(default=None),
                  x_confirm_execution: str | None = Header(default=None)):
    authorize(authorization)
    require_host_toolchain()
    require_approval(x_confirm_execution, "toolchain execution")
    language = _language(body.language)
    info = _capability(language)
    if not info["installed"]:
        raise HTTPException(409, f"{language} toolchain is missing. {info['install_hint']}")
    root = workspace(body.project)
    relative = None
    if body.path:
        try:
            relative = toolchains.safe_relative(body.path)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        target = resolve(body.project, relative)
        if not target.is_file():
            raise HTTPException(404, "Target file not found")
    if body.action in ("check", "run") and not relative:
        raise HTTPException(400, "A path is required for check and run")
    try:
        return toolchains.execute(language, body.action, root, target=relative,
                                  timeout=body.timeout)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except OSError as exc:
        raise HTTPException(500, f"Unable to launch toolchain: {exc}")


async def _chat(base, model, key, messages, max_tokens=4096) -> str:
    async with httpx.AsyncClient(timeout=180, trust_env=False,
                                 follow_redirects=False) as client:
        response = await client.post(
            base + "/chat/completions",
            headers={"Authorization": "Bearer " + key},
            json={"model": model, "messages": messages, "temperature": 0.1,
                  "max_tokens": max(64, min(int(max_tokens), 8192))},
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Model returned no source text")
    return content


def _prompt(language, relative, instruction, existing, feedback, attempt):
    return (
        f"Task: {instruction}\n"
        f"Language: {language}\n"
        f"File to write: {relative}\n"
        f"Attempt: {attempt}\n"
        f"Toolchain verification: this file is compiled or executed, and the program "
        f"must be self-contained and non-interactive.\n"
        + (f"Existing source to preserve where possible:\n{existing[:60000]}\n" if existing else "")
        + (f"Previous verification failure to fix:\n{feedback[-6000:]}\n" if feedback else "")
    )


async def solve_task(*, project, instruction, language="auto", path=None,
                     attempts=2, verify_run=True, apply=None) -> dict:
    root = workspace(project)
    chosen = toolchains.choose_language(instruction, language, root)
    name = chosen["language"]
    info = _capability(name)
    if not info["installed"]:
        raise HTTPException(
            409,
            f"{name} toolchain is not installed on this computer. {info['install_hint']}",
        )
    spec = toolchains.get_spec(name)
    default_file = spec.get("default_file")
    if not path and not default_file:
        raise HTTPException(
            400, f"{name} has no default starter file; pass an explicit path")
    relative = toolchains.safe_relative(path or default_file)
    live = resolve(project, relative)
    if live.is_dir():
        raise HTTPException(400, "Target path is a directory")
    previous = current(live) if live.is_file() else ""
    if len(previous.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise HTTPException(413, "Target file is too large for an autonomous trial")

    base, model, key = model_config()
    max_tokens = int(os.getenv("AGENT_PROPOSAL_MAX_TOKENS", "4096"))
    system_prompt = (
        f"You are an autonomous polyglot software engineer writing {name}. "
        "Return ONLY the complete contents of the requested file. No markdown "
        "fences, no explanation, no test output. Preserve unrelated behavior when "
        "editing an existing file. Never claim tests passed; the harness runs them."
    )
    trial = Path(tempfile.mkdtemp(prefix="polyglot-solve-"))
    tests = []
    candidate = previous
    passed = False
    feedback = ""
    try:
        target = trial / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, max(1, min(int(attempts), 3)) + 1):
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _prompt(name, relative, instruction,
                                                    previous, feedback, attempt)},
            ]
            try:
                generated = await _chat(base, model, key, messages, max_tokens)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                raise HTTPException(502, f"Model did not return source: {type(exc).__name__}")
            candidate = extract_source(generated)
            if not candidate.strip() or len(candidate.encode("utf-8")) > MAX_SOURCE_BYTES:
                raise HTTPException(502, "Model returned empty or oversized source")
            target.write_text(candidate, encoding="utf-8")
            result = verify(name, trial, relative, verify_run=verify_run)
            tests.append({"attempt": attempt, "passed": result["passed"], **result})
            if result["passed"]:
                passed = True
                break
            output = []
            for key_name in ("check", "run"):
                step = result.get(key_name)
                if step:
                    for item in step.get("steps", []):
                        output.append(item.get("stdout", "") + item.get("stderr", ""))
            feedback = "\n".join(output)[-6000:] or result.get("note", "verification failed")
    finally:
        if os.getenv("POLYGLOT_KEEP_TRIALS") != "1":
            shutil.rmtree(trial, ignore_errors=True)

    diff_text = "".join(difflib.unified_diff(
        previous.splitlines(keepends=True), candidate.splitlines(keepends=True),
        fromfile="current/" + relative, tofile="proposed/" + relative))
    proposal = create_record(project, [{
        "path": relative, "expected_sha256": digest(previous),
        "content": candidate, "diff": diff_text,
    }])

    should_apply = autonomy() if apply is None else bool(apply)
    applied = False
    apply_error = None
    live_verification = None
    if should_apply and candidate != previous:
        try:
            apply_record(project, proposal["proposal_id"], proposal["proposal_hash"])
            applied = True
        except HTTPException as exc:
            apply_error = str(exc.detail)
        except OSError as exc:
            apply_error = f"{type(exc).__name__}: {exc}"
        if applied:
            live_verification = verify(name, root, relative, verify_run=verify_run)

    return {
        "ok": True,
        "project": project,
        "language": name,
        "language_reason": chosen["reason"],
        "target": relative,
        "toolchain": info,
        "trial_passed": passed,
        "attempts": len(tests),
        "tests": tests,
        "proposal": proposal,
        "applied": applied,
        "apply_error": apply_error,
        "live_verification": live_verification,
        "changed": candidate != previous,
    }


def run_solve_job(payload: dict) -> dict:
    """Worker handler for queued autonomous solves."""
    try:
        result = asyncio.run(solve_task(
            project=payload["project"], instruction=payload["instruction"],
            language=payload.get("language", "auto"), path=payload.get("path"),
            attempts=int(payload.get("attempts", 2)),
            verify_run=bool(payload.get("verify_run", True)),
            apply=payload.get("apply"),
        ))
    except HTTPException as exc:
        raise RuntimeError(f"HTTP {exc.status_code}: {exc.detail}")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid solve payload: {exc}")
    if not result.get("trial_passed"):
        raise RuntimeError(
            f"Autonomous {result.get('language')} trial did not pass verification "
            f"after {result.get('attempts')} attempt(s); proposal retained for review"
        )
    return result


def run_check_job(payload: dict) -> dict:
    """Worker handler for a queued toolchain check."""
    if not host_toolchain():
        raise RuntimeError("Host toolchain execution is disabled")
    root = workspace(payload["project"])
    relative = toolchains.safe_relative(payload["path"])
    return toolchains.execute(payload["language"], payload.get("action", "check"),
                              root, target=relative)


@router.post("/solve")
async def solve(body: SolveRequest, authorization: str | None = Header(default=None),
                x_confirm_execution: str | None = Header(default=None),
                x_confirm_change: str | None = Header(default=None)):
    authorize(authorization)
    require_host_toolchain()
    require_approval(x_confirm_execution, "autonomous coding on this computer")
    if body.queue:
        if not autonomy():
            raise HTTPException(428, "Queued autonomous jobs require AGENT_AUTONOMY=1")
        require_approval(x_confirm_change, "applying generated code")
        from . import worker
        try:
            job = worker.enqueue(
                "polyglot.solve",
                {"project": body.project, "instruction": body.instruction,
                 "language": body.language, "path": body.path,
                 "attempts": body.attempts, "verify_run": body.verify_run,
                 "apply": body.apply},
                priority=body.priority,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"queued": True, **job}
    wants_apply = autonomy() if body.apply is None else body.apply
    if wants_apply:
        require_approval(x_confirm_change, "applying generated code")
    return await solve_task(
        project=body.project, instruction=body.instruction,
        language=body.language, path=body.path, attempts=body.attempts,
        verify_run=body.verify_run, apply=body.apply,
    )
