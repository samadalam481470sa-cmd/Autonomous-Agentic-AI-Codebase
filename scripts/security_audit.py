#!/usr/bin/env python3
"""Static security audit for this repository.

Checks source, configuration and CI for the classes of weakness that a running
process cannot detect about itself:

* committed credentials (provider tokens, private keys, env assignments)
* dangerous sinks (shell execution, eval/exec, pickle, unsafe YAML, TLS
  verification disabled)
* supply-chain pinning (unpinned dependencies, missing lockfiles, CI actions
  referenced by mutable tags)
* exposed artifacts (``.env``, SQLite databases, private keys)
* world-writable files and a root container user

Findings never include the matched secret itself; only the rule, path and line.

Usage::

    python scripts/security_audit.py
    python scripts/security_audit.py --json
    python scripts/security_audit.py --fail-on high
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.content_safety import SECRET_RULES  # noqa: E402

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "third_party", "upstream",
    "workspaces", "dist", ".local", ".idea", ".vscode", "build", "coverage",
}
TEXT_SUFFIXES = {
    ".py", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx", ".json", ".yml",
    ".yaml", ".toml", ".ini", ".cfg", ".sh", ".bash", ".html", ".css",
    ".env", ".example", ".md", ".txt", ".rs", ".sql", ".dockerfile",
}
SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
MAX_BYTES = 2_000_000
SELF = Path(__file__).resolve()

SINK_RULES = [
    ("critical", "shell execution", re.compile(r"\bshell\s*=\s*True\b")),
    ("high", "os.system", re.compile(r"\bos\.system\s*\(")),
    ("high", "python eval", re.compile(r"(?<![\w.])eval\s*\(")),
    ("high", "python exec", re.compile(r"(?<![\w.])exec\s*\(")),
    ("high", "pickle deserialization", re.compile(r"\bpickle\.loads?\s*\(")),
    ("high", "unsafe yaml load", re.compile(r"\byaml\.load\s*\((?!.*Loader)")),
    ("high", "disabled TLS verification", re.compile(r"\bverify\s*=\s*False\b")),
]
UNPINNED = re.compile(r"^[\^~*]|^latest$")
SHA_PIN = re.compile(r"@[0-9a-f]{40}$")
# Strict env-file assignment. Scanning per line avoids the generic rule's
# newline-spanning false positives on ordinary code and placeholders.
ENV_ASSIGN = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*=\s*(['\"]?)([^\s'\"#]{6,})\2\s*$")
ENV_SECRET_NAME = re.compile(
    r"SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL")
CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".sql"}


def finding(severity: str, rule: str, path: Path, line: int = 0,
            detail: str = "") -> dict:
    try:
        relative = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        relative = path.name
    return {"severity": severity, "rule": rule, "path": relative,
            "line": line, "detail": detail}


def iter_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            try:
                if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield path


def is_text(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES or path.name in {
            "Dockerfile", "Makefile", "LICENSE", "Procfile"}:
        return True
    return suffix == ""


def read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        return None


def scan_secrets(path: Path, text: str, findings: list[dict]) -> None:
    in_tests = ("tests" in path.parts or path.name.startswith("test_")
                or ".test." in path.name or ".spec." in path.name)
    in_docs = "docs" in path.parts or path.suffix.lower() == ".md"
    if in_tests or in_docs:
        return
    lines = text.splitlines()
    is_placeholder = path.suffix.lower() in {".example", ".sample", ".template"} \
        or path.name.endswith((".example", ".sample", ".template"))
    for kind, pattern, _strategy in SECRET_RULES:
        if kind == "env_secret":
            if is_placeholder:
                continue
            for number, line in enumerate(lines, 1):
                match = ENV_ASSIGN.match(line)
                if match and ENV_SECRET_NAME.search(match.group(1)):
                    findings.append(finding(
                        "critical", f"secret:{kind}", path, number,
                        "remove the value and rotate the credential"))
            continue
        if kind == "uri_credentials" and path.suffix.lower() not in CONFIG_SUFFIXES:
            continue
        if kind == "private_key":
            for match in pattern.finditer(text):
                findings.append(finding(
                    "critical", f"secret:{kind}", path,
                    text.count("\n", 0, match.start()) + 1,
                    "remove the value and rotate the credential"))
            continue
        for number, line in enumerate(lines, 1):
            if pattern.search(line):
                findings.append(finding(
                    "critical", f"secret:{kind}", path, number,
                    "remove the value and rotate the credential"))


def scan_sinks(path: Path, text: str, findings: list[dict]) -> None:
    if path.suffix.lower() not in {".py", ".js", ".cjs", ".mjs", ".ts", ".tsx"}:
        return
    if "tests" in path.parts:
        return
    for severity, rule, pattern in SINK_RULES:
        for match in pattern.finditer(text):
            findings.append(finding(severity, rule, path,
                                    text.count("\n", 0, match.start()) + 1,
                                    "review this sink; prefer a safe API"))


def scan_exposed(path: Path, text: str, findings: list[dict]) -> None:
    name = path.name.lower()
    if name in {"id_rsa", "id_ed25519", "id_dsa"} or path.suffix.lower() in {".pem", ".key"}:
        findings.append(finding("critical", "private-key-file", path, 1,
                                "remove from the repository and rotate"))
    if path.suffix.lower() == ".sqlite3":
        findings.append(finding("medium", "database-in-repository", path, 1,
                                "keep databases outside version control"))
    if name == ".env":
        findings.append(finding("low", "local-env-file", path, 1,
                                "never commit; keep it untracked"))


def scan_permissions(path: Path, findings: list[dict]) -> None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & stat.S_IWOTH:
        findings.append(finding("high", "world-writable", path, 1,
                                "remove the other-write bit"))


def scan_manifests(path: Path, text: str, findings: list[dict]) -> None:
    if path.name == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for name, version in (data.get(section) or {}).items():
                if isinstance(version, str) and UNPINNED.search(version):
                    findings.append(finding("low", "unpinned-dependency", path, 1,
                                            f"{name} uses {version}"))
        if not (path.parent / "package-lock.json").is_file() and \
                not (path.parent / "yarn.lock").is_file() and \
                not (path.parent.parent / "package-lock.json").is_file():
            findings.append(finding("medium", "missing-lockfile", path, 1,
                                    "commit a lockfile to pin the dependency tree"))


def scan_workflows(path: Path, text: str, findings: list[dict]) -> None:
    if ".github" not in path.parts or path.suffix.lower() not in {".yml", ".yaml"}:
        return
    for match in re.finditer(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", text):
        reference = match.group(1).strip()
        if reference.startswith("./") or reference.startswith("docker://"):
            continue
        if not SHA_PIN.search(reference):
            findings.append(finding("low", "unpinned-action", path,
                                    text.count("\n", 0, match.start()) + 1,
                                    f"{reference} should be pinned to a commit SHA"))


def scan_container(path: Path, text: str, findings: list[dict]) -> None:
    if path.name != "Dockerfile":
        return
    users = re.findall(r"(?mi)^\s*USER\s+(\S+)", text)
    if not users or users[-1].lower() in {"root", "0", "0:0"}:
        findings.append(finding("high", "root-container-user", path, 1,
                                "set a non-root USER"))


def gitignore_check(findings: list[dict]) -> None:
    gitignore = ROOT / ".gitignore"
    if not gitignore.is_file():
        findings.append(finding("medium", "missing-gitignore", gitignore, 1,
                                "add .env and database files"))
        return
    text = read_text(gitignore) or ""
    for pattern, rule in ((".env", "env-not-ignored"), ("sqlite", "database-not-ignored")):
        if pattern not in text:
            findings.append(finding("medium", rule, gitignore, 1,
                                    f"add {pattern} to .gitignore"))


def run() -> list[dict]:
    findings: list[dict] = []
    for path in iter_files():
        if path.resolve() == SELF:
            continue
        text = read_text(path) if is_text(path) else None
        scan_permissions(path, findings)
        scan_exposed(path, text or "", findings)
        if text is None:
            continue
        scan_secrets(path, text, findings)
        scan_sinks(path, text, findings)
        scan_manifests(path, text, findings)
        scan_workflows(path, text, findings)
        scan_container(path, text, findings)
    gitignore_check(findings)
    findings.sort(key=lambda item: (-SEVERITY_ORDER[item["severity"]],
                                    item["path"], item["line"]))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--fail-on", default="high",
                        choices=["none", "low", "medium", "high", "critical"],
                        help="exit non-zero at or above this severity")
    args = parser.parse_args()
    findings = run()
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for item in findings:
        counts[item["severity"]] += 1
    threshold = SEVERITY_ORDER[args.fail_on] if args.fail_on != "none" else 99
    failed = any(SEVERITY_ORDER[item["severity"]] >= threshold for item in findings)
    if args.json:
        print(json.dumps({"root": str(ROOT), "summary": counts,
                          "findings": findings, "failed": failed}, indent=2))
    else:
        for item in findings:
            location = f"{item['path']}:{item['line']}" if item["line"] else item["path"]
            detail = f" - {item['detail']}" if item["detail"] else ""
            print(f"[{item['severity'].upper():8}] {item['rule']:28} {location}{detail}")
        print()
        print("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
        print(f"Threshold {args.fail_on}: {'FAILED' if failed else 'passed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
