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
    "You are a coding agent solving one self-contained benchmark task. "
    "Replace the complete contents of the existing starter file with working code. "
    "Return one JSON object and nothing else. Its only key is files; files maps "
    "an existing file name to its complete new text. Escape newlines as \\n. "
    "Do not invent a path, do not copy this instruction as the answer, do not "
    "change tests, and do not explain outside the JSON."
)
SINGLE_SYSTEM_PROMPT = (
    "You are a coding agent. Return only the complete replacement contents of the "
    "target file. Do not use JSON, Markdown fences, or explanations. The response "
    "must be runnable source code, not a placeholder."
)


def _extract_code(text: str) -> str:
    value = (text or "").strip()
    fenced = re.search(r"```[a-zA-Z0-9_-]*\s*\n(.*?)```", value, re.DOTALL)
    if fenced:
        value = fenced.group(1)
    elif value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


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
    if not files:
        raise ValueError("task has no starter file")
    owned = client is None
    http = client or httpx.Client(timeout=180, trust_env=False, follow_redirects=False)

    def ask(system, user, max_tokens=4096):
        response = http.post(
            config["base_url"] + "/chat/completions",
            headers={"Authorization": "Bearer " + config["api_key"]},
            json={
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("model returned an empty response")
        return content

    try:
        if len(files) == 1:
            target, original = next(iter(files.items()))
            user = (
                "Task:\n" + prompt + f"\n\nCurrent file {target}:\n" + original
                + f"\n\nReturn only the complete replacement code for {target}."
            )
            last_error = None
            for _ in range(2):
                content = ask(SINGLE_SYSTEM_PROMPT, user)
                code = _extract_code(content)
                if (
                    not code
                    or code == original.strip()
                    or "NotImplementedError" in code
                    or "not implemented" in code.lower()
                    or (code.lstrip().startswith("{") and '"files"' in code)
                ):
                    last_error = ValueError("model returned a placeholder or unchanged file")
                    user += "\n\nReturn real implementation code, not a placeholder or explanation."
                    continue
                apply_plan(workspace, {target: code + "\n"})
                return {target: code + "\n"}
            raise ValueError("model did not return usable code: " + str(last_error))

        targets = ", ".join(files)
        user = (
            "Task:\n" + prompt + "\n\nCurrent files:\n"
            + "\n\n".join(f"--- {name} ---\n{content}" for name, content in files.items())
            + f"\n\nTarget files: {targets}. Return JSON only, using existing file names."
        )
        last_error = None
        for _ in range(2):
            content = ask(SYSTEM_PROMPT, user)
            try:
                plan = parse_plan(content)
                if not (set(plan) & set(files)):
                    raise ValueError("plan did not modify an existing starter file")
                if all(plan.get(name) == files.get(name) for name in plan):
                    raise ValueError("plan did not change the starter file")
            except (ValueError, json.JSONDecodeError) as error:
                last_error = error
                user += "\n\nYour previous reply was invalid: " + str(error) + ". Return JSON using an existing file name and real code."
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
