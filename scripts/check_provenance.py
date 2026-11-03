#!/usr/bin/env python3
"""Verify the repository's first-party / upstream separation.

This is a structural gate, not a malware scanner. It ensures:
  * The two upstream trees are pinned git submodules, never copied-in directories.
  * First-party code cannot reference, import, or package the GPL-3.0
    AgenticSeek tree. The only integration is the authenticated loopback HTTP
    adapter.
  * Every vendored third-party tree is declared in the license policy.
  * The first-party license remains MIT.
"""

from __future__ import annotations

import argparse
import configparser
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "security" / "license-policy.json"
AGENTICSEEK = "upstream/agenticseek"
CODE_OSS = "upstream/code-oss"
AGENTICSEEK_ADAPTER = Path("services/api/agenticseek.py")
ALLOWED_REFERENCES = {
    ".gitmodules",
    "README.md",
    "docs/AGENTICSEEK_INTEGRATION.md",
    "docs/OPEN_SOURCE_REFERENCES.md",
    "docs/UPLOADED_SOURCE_PROVENANCE.md",
    "security/license-policy.json",
    "scripts/check_provenance.py",
    "tests/test_provenance.py",
}
FORBIDDEN_IMPORT = re.compile(r"^\s*(?:from|import)\s+agenticseek\b", re.MULTILINE)
FORBIDDEN_PATH = re.compile(r"upstream/agenticseek|Fosowl/agenticSeek", re.IGNORECASE)
FORBIDDEN_ADAPTER_CODE = (
    "subprocess",
    "os.system",
    "os.popen",
    "eval(",
    "exec(",
    "sys.path",
    "import agenticseek",
    "from agenticseek",
)


class ProvenanceError(RuntimeError):
    pass


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ProvenanceError(result.stderr.strip() or f"git {' '.join(arguments)} failed")
    return result.stdout


def submodules(root: Path) -> dict[str, dict[str, str]]:
    config = configparser.ConfigParser()
    path = root / ".gitmodules"
    if not path.is_file():
        raise ProvenanceError(".gitmodules is missing")
    config.read(path, encoding="utf-8")
    result: dict[str, dict[str, str]] = {}
    for section in config.sections():
        if not section.startswith("submodule "):
            continue
        entry = dict(config.items(section))
        result[entry.get("path", "")] = entry
    return result


def tracked_files(root: Path) -> list[str]:
    # Include untracked, non-ignored files so the gate also protects staged
    # work before CI ever sees a commit.
    return [name for name in git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0") if name]


def find_forbidden_references(files: dict[str, str]) -> list[str]:
    violations = []
    for name, text in files.items():
        normalized = name.replace("\\", "/")
        if normalized in ALLOWED_REFERENCES:
            continue
        if normalized.startswith(("upstream/", "third_party/", "docs/", "tests/")):
            continue
        path_hit = bool(FORBIDDEN_PATH.search(text))
        if path_hit:
            violations.append(f"{normalized}: first-party code references the GPL-3.0 upstream tree")
        if normalized.endswith(".py") and FORBIDDEN_IMPORT.search(text):
            violations.append(f"{normalized}: imports external agenticseek code")
        if (
            normalized in {"Dockerfile", "compose.yaml", "pyproject.toml"}
            and "upstream/" in text
            and not path_hit
        ):
            violations.append(f"{normalized}: build or packaging file includes an upstream tree")
    return list(dict.fromkeys(violations))


def audit(root: Path = ROOT) -> dict:
    checks: list[str] = []
    violations: list[str] = []
    policy = json.loads((root / "security" / "license-policy.json").read_text(encoding="utf-8"))

    configured = submodules(root)
    checks.append(f"git submodules configured: {len(configured)}")
    for path, url in (
        (CODE_OSS, "https://github.com/microsoft/vscode.git"),
        (AGENTICSEEK, "https://github.com/Fosowl/agenticSeek.git"),
    ):
        entry = configured.get(path)
        if not entry:
            violations.append(f".gitmodules: missing pinned submodule {path}")
        elif entry.get("url", "").rstrip("/") != url.rstrip("/"):
            violations.append(f".gitmodules: {path} points at {entry.get('url')} instead of {url}")

    index_lines = git(root, "ls-files", "-s").splitlines()
    gitlinks = {}
    for line in index_lines:
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "160000":
            gitlinks[parts[3]] = parts[1]
    for path in (CODE_OSS, AGENTICSEEK):
        if path not in gitlinks:
            violations.append(f"{path} is not recorded as a git submodule (mode 160000)")
        else:
            checks.append(f"{path} pinned at {gitlinks[path][:12]}")

    files: dict[str, str] = {}
    for name in tracked_files(root):
        if name.startswith(("upstream/", "third_party/", ".git/")):
            continue
        path = root / name
        if not path.is_file() or path.stat().st_size > 1_500_000:
            continue
        try:
            files[name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
    violations.extend(find_forbidden_references(files))
    checks.append(f"scanned {len(files)} tracked first-party files for upstream references")

    adapter = root / AGENTICSEEK_ADAPTER
    if not adapter.is_file():
        violations.append(f"{AGENTICSEEK_ADAPTER} is missing")
    else:
        source = adapter.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_ADAPTER_CODE:
            if forbidden in source:
                violations.append(f"{AGENTICSEEK_ADAPTER}: forbidden boundary-breaking code: {forbidden}")
        for required in ("127.0.0.1", "AGENTICSEEK_URL", "AGENTICSEEK_API_TOKEN", "httpx"):
            if required not in source:
                violations.append(f"{AGENTICSEEK_ADAPTER}: missing loopback/token boundary marker: {required}")
        if "upstream/agenticseek" in source:
            violations.append(f"{AGENTICSEEK_ADAPTER}: references the upstream tree")
        checks.append("AgenticSeek adapter is HTTP-only, loopback-only, and token-gated")

    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith("MIT License"):
        violations.append("First-party LICENSE is not MIT")
    else:
        checks.append("first-party LICENSE is MIT")

    declared = {
        Path(entry["path"]).as_posix()
        for entry in policy.get("vendored", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    third_party = root / "third_party"
    if third_party.is_dir():
        for child in sorted(third_party.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            relative = child.relative_to(root).as_posix()
            if relative not in declared:
                violations.append(f"third_party/{child.name} is not declared in the license policy")
        checks.append(f"third_party directories declared: {len(declared)}")

    submodule_entries = {
        entry.get("path") for entry in policy.get("optional_submodules", []) if isinstance(entry, dict)
    }
    for path in (CODE_OSS, AGENTICSEEK):
        if path not in submodule_entries:
            violations.append(f"license policy does not declare optional submodule {path}")
    agent = next(
        (entry for entry in policy.get("optional_submodules", []) if entry.get("path") == AGENTICSEEK),
        None,
    )
    if not agent or agent.get("license") != "GPL-3.0":
        violations.append("license policy must record AgenticSeek as GPL-3.0")
    elif "separate" not in str(agent.get("relationship", "")).lower():
        violations.append("license policy must describe AgenticSeek as a separate process")

    return {
        "passed": not violations,
        "checks": checks,
        "violations": violations,
        "submodules": {path: gitlinks.get(path) for path in (CODE_OSS, AGENTICSEEK)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)
    try:
        result = audit(Path(args.root).resolve())
    except (ProvenanceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PROVENANCE ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for check in result["checks"]:
            print(f"  ok: {check}")
        for violation in result["violations"]:
            print(f"  BLOCKED: {violation}", file=sys.stderr)
        print("PASS: upstream and first-party code are separated." if result["passed"] else "FAILED: provenance boundary violated.")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
