#!/usr/bin/env python3
"""One-shot model agent for the 30-task coding benchmark.

The benchmark runner invokes this inside a disposable task directory with
BENCHMARK_PROMPT set. The model gets the task and current files, and must return
complete replacement files as JSON. No tools, shell, network from generated code
or test-file writes are allowed. A missing model configuration exits non-zero so
a run can never be mistaken for a score.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx

MAX_FILE_BYTES = 100_000
MAX_TOTAL_BYTES = 300_000
MAX_PROMPT_CHARS = 60_000
SYSTEM_PROMPT = (
    "You are solving a self-contained coding benchmark. Return exactly one JSON "
    'object and no markdown: {"files":{"relative/path":"complete file content"}}. '
    "Include every file you change with its complete content. Do not change or "
    "create tests, do not use the network, and do not explain outside the JSON."
)


def settings(env=None) -> dict:
    env = os.environ if env is None else env
    local = env.get("LOCAL_MODEL_ONLY") == "1"
    base = (env.get("MODEL_BASE_URL")
            or (env.get("LOCAL_MODEL_BASE_URL") if local else "https://api.openai.com/v1"))
    key = env.get("MODEL_API_KEY") or ("local" if local else "")
    model = env.get("MODEL_NAME") or (env.get("LOCAL_MODEL_NAME") if local else "gpt-4.1-mini")
    if not base or not key or not model:
        raise RuntimeError(
            "No model configured: set MODEL_API_KEY and MODEL_NAME, or "
            "LOCAL_MODEL_ONLY=1 with LOCAL_MODEL_BASE_URL and LOCAL_MODEL_NAME."
        )
    return {"base_url": base.rstrip("/"), "api_key": key, "model": model}


def current_files(root: Path) -> dict[str, str]:
    files = {}
    used = 0
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts or not path.is_file():
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        remaining = MAX_PROMPT_CHARS - used
        if remaining <= 0:
            break
        files[path.relative_to(root).as_posix()] = content[:remaining]
        used += len(content[:remaining])
    return files


def parse_plan(text: str) -> dict[str, str]:
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z]*\s*", "", value)
        value = re.sub(r"\s*```$", "", value).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model output was not a JSON object")
        parsed = json.loads(value[start:end + 1])
    if not isinstance(parsed, dict) or not isinstance(parsed.get("files"), dict):
        raise ValueError("model output must contain a files object")
    files = parsed["files"]
    if not files:
        raise ValueError("model returned no files")
    result = {}
    total = 0
    for name, content in files.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise ValueError("file entries must be strings")
        target = Path(name)
        if target.is_absolute() or ".." in target.parts or not name.strip():
            raise ValueError("file path escapes the task directory")
        if ".git" in target.parts:
            raise ValueError("refusing to write git metadata")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError("file exceeds the size limit")
        total += len(encoded)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("total write exceeds the size limit")
        result[name] = content
    return result


def apply_plan(root: Path, files: dict[str, str]) -> None:
    root = root.resolve()
    destinations = []
    for name, content in files.items():
        target = (root / name).resolve()
        if not target.is_relative_to(root):
            raise ValueError("file path escapes the task directory")
        destinations.append((target, content))
    for target, content in destinations:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def solve(prompt: str, workspace: Path, *, client=None, env=None) -> dict[str, str]:
    config = settings(env)
    files = current_files(workspace)
    user = (
        "Task:\n" + prompt + "\n\nCurrent files:\n"
        + "\n\n".join(f"--- {name} ---\n{content}" for name, content in files.items())
        + "\n\nReturn the complete changed file(s) as JSON."
    )
    owned = client is None
    http = client or httpx.Client(timeout=180, trust_env=False, follow_redirects=False)
    try:
        last_error = None
        for _ in range(2):
            response = http.post(
                config["base_url"] + "/chat/completions",
                headers={"Authorization": "Bearer " + config["api_key"]},
                json={
                    "model": config["model"],
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0,
                    "max_tokens": 4096,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("model returned an empty response")
            try:
                plan = parse_plan(content)
            except (ValueError, json.JSONDecodeError) as error:
                last_error = error
                user += "\n\nYour previous reply was invalid: " + str(error) + ". Return JSON only."
                continue
            apply_plan(workspace, plan)
            return plan
        raise ValueError("model did not return a valid file plan: " + str(last_error))
    finally:
        if owned:
            http.close()


def main() -> int:
    prompt = os.getenv("BENCHMARK_PROMPT", "")
    if not prompt:
        print("benchmark agent: BENCHMARK_PROMPT is not set", file=sys.stderr)
        return 2
    try:
        plan = solve(prompt, Path.cwd())
    except Exception as error:
        print("benchmark agent: " + str(error)[:500], file=sys.stderr)
        return 2
    print("benchmark agent wrote: " + ", ".join(sorted(plan)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
