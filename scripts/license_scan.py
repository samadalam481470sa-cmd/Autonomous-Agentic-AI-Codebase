#!/usr/bin/env python3
"""Fail-closed license scan for every dependency ecosystem in this repository.

Scans:
  * installed Python distributions (PEP 639 expressions, metadata classifiers)
  * declared Python dependencies from pyproject.toml and requirements*.txt
  * installed Node packages (or a package-lock fallback)
  * resolved Rust crates through cargo metadata
  * vendored third-party source trees
  * the model registry and bundled-model distribution manifest

Exit codes: 0 approved, 1 policy violation, 2 scan/configuration error.
Unknown licenses, missing metadata, and missing declared approvals all block.
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.licensing.policy import (  # noqa: E402
    check_model_manifest,
    classify_package,
    evaluate_license,
    infer_license,
    load_json,
    normalize_license,
    validate_model_policy,
)

SCHEMA_VERSION = 1


class ScanError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name)).strip().lower()


def dedupe(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for record in records:
        key = (
            str(record.get("ecosystem")),
            normalized_name(record.get("name", "")),
            str(record.get("version")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


# ---------------------------------------------------------------------------
# Python: installed distributions and declared manifests
# ---------------------------------------------------------------------------


def scan_installed_python(policy: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for distribution in metadata.distributions():
        meta = distribution.metadata
        name = meta.get("Name") if meta else None
        if not name:
            continue
        try:
            version = distribution.version or "unknown"
        except Exception:
            version = "unknown"
        license_value = None
        classifiers: list[str] = []
        if meta:
            license_value = meta.get("License-Expression") or meta.get("License")
            classifiers = meta.get_all("Classifier") or []
        records.append(
            classify_package(
                ecosystem="python",
                name=str(name),
                version=str(version),
                license_value=str(license_value) if license_value else None,
                classifiers=classifiers,
                policy=policy,
            )
        )
    return dedupe(records)


def _requirement_names(text: str) -> list[str]:
    names = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if " @ " in line:
            candidate = line.split(" @ ", 1)[0].strip()
        else:
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            candidate = match.group(1) if match else ""
        if candidate and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", candidate):
            names.append(candidate)
    return names


def scan_declared_python(root: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    declared = {
        normalized_name(name): entry
        for name, entry in (policy.get("declared_dependencies", {}).get("python", {}) or {}).items()
    }
    first_party = {
        normalized_name(name)
        for name in policy.get("first_party", {}).get("python_distributions", [])
    }
    names: list[str] = []
    for path in sorted(root.glob("requirements*.txt")):
        names.extend(_requirement_names(path.read_text(encoding="utf-8")))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {}) or {}
        names.extend(_requirement_names("\n".join(project.get("dependencies", []) or [])))
        for values in (project.get("optional-dependencies", {}) or {}).values():
            names.extend(_requirement_names("\n".join(values or [])))
    records = []
    for name in sorted({normalized_name(item) for item in names}):
        if not name or name in first_party:
            continue
        entry = declared.get(name)
        if entry is None:
            records.append(
                {
                    "ecosystem": "declared-python",
                    "name": name,
                    "version": "declared",
                    "declared_license": None,
                    "license": "UNKNOWN",
                    "status": "blocked",
                    "reason": "Declared dependency has not been reviewed in security/license-policy.json",
                }
            )
            continue
        verdict = evaluate_license(str(entry.get("license", "")), policy)
        records.append(
            {
                "ecosystem": "declared-python",
                "name": name,
                "version": "declared",
                "declared_license": entry.get("license"),
                "license": entry.get("license"),
                "status": verdict["status"],
                "reason": f"{entry.get('reason', 'Declared dependency')} ({verdict['reason']})",
            }
        )
    return dedupe(records)


# ---------------------------------------------------------------------------
# Node packages
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScanError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ScanError(f"{path} must contain a JSON object")
    return value


def _infer_license_from_files(directory: Path) -> str | None:
    if not directory.is_dir():
        return None
    for candidate in sorted(directory.iterdir()):
        if not candidate.is_file():
            continue
        upper = candidate.name.upper()
        if not upper.startswith(("LICENSE", "COPYING")):
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")[:16000]
        except OSError:
            continue
        detected = infer_license(text)
        if detected:
            return detected
    return None


def _node_license(data: dict[str, Any], directory: Path) -> str | None:
    value = data.get("license")
    if isinstance(value, dict):
        value = value.get("type") or value.get("name")
    if not value and isinstance(data.get("licenses"), list):
        types = []
        for entry in data["licenses"]:
            if isinstance(entry, dict) and entry.get("type"):
                types.append(str(entry["type"]))
            elif isinstance(entry, str):
                types.append(entry)
        value = " OR ".join(dict.fromkeys(types)) if types else None
    if isinstance(value, str) and value.lower().startswith("see license in "):
        filename = value[len("see license in ") :].strip()
        candidate = directory / filename
        if candidate.is_file():
            try:
                return infer_license(candidate.read_text(encoding="utf-8", errors="replace")[:16000])
            except OSError:
                return None
        return None
    if value:
        return str(value)
    return _infer_license_from_files(directory)


def _installed_node_packages(node_modules: Path) -> list[tuple[str, str, str | None, Path]]:
    packages = []
    if not node_modules.is_dir():
        return packages
    for directory, dirnames, filenames in os.walk(node_modules):
        dirnames[:] = sorted(name for name in dirnames if name not in {".bin", ".cache"})
        if "package.json" not in filenames:
            continue
        relative = Path(directory).relative_to(node_modules)
        parts = relative.parts
        # Dual ESM/CJS packages contain marker package.json files such as
        # dist/commonjs/package.json. Only <name>/package.json and
        # @scope/<name>/package.json are real package roots.
        if "node_modules" in parts:
            tail = len(parts) - 1 - list(reversed(parts)).index("node_modules")
            parts = parts[tail + 1 :]
        if not (len(parts) == 1 or (len(parts) == 2 and parts[0].startswith("@"))):
            continue
        path = Path(directory) / "package.json"
        try:
            data = _read_json(path)
        except ScanError:
            continue
        if data.get("link") is True:
            continue
        name = str(data.get("name") or Path(directory).relative_to(node_modules).as_posix())
        version = str(data.get("version") or "unknown")
        packages.append((name, version, _node_license(data, Path(directory)), Path(directory)))
    return packages


def _lock_node_packages(directory: Path, lock: dict[str, Any]) -> list[tuple[str, str, str | None, Path]]:
    packages = []
    entries = lock.get("packages")
    if not isinstance(entries, dict):
        return packages
    for key, value in entries.items():
        if not key or not isinstance(value, dict) or value.get("link") is True:
            continue
        name = value.get("name")
        if not name:
            marker = "node_modules/"
            name = key.rsplit(marker, 1)[-1] if marker in key else key
        version = str(value.get("version") or "unknown")
        license_value = value.get("license")
        if isinstance(license_value, list):
            license_value = " OR ".join(str(item) for item in license_value)
        if not license_value:
            license_value = _infer_license_from_files(directory / key)
        packages.append((str(name), version, str(license_value) if license_value else None, directory / key))
    return packages


def scan_node(directory: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    directory = directory.resolve()
    manifest_path = directory / "package.json"
    if not manifest_path.is_file():
        raise ScanError(f"Missing package.json: {manifest_path}")
    manifest = _read_json(manifest_path)
    node_modules = directory / "node_modules"
    lock_path = directory / "package-lock.json"
    if node_modules.is_dir():
        installed = _installed_node_packages(node_modules)
    elif lock_path.is_file():
        installed = _lock_node_packages(directory, _read_json(lock_path))
    else:
        declared = {
            **(manifest.get("dependencies") or {}),
            **(manifest.get("devDependencies") or {}),
        }
        if declared:
            raise ScanError(
                f"No node_modules or package-lock.json in {directory}; run npm install before scanning"
            )
        installed = []

    records = []
    root_name = str(manifest.get("name") or directory.name)
    records.append(
        classify_package(
            ecosystem="npm",
            name=root_name,
            version=str(manifest.get("version") or "unknown"),
            license_value=_node_license(manifest, directory),
            policy=policy,
        )
    )
    for name, version, license_value, package_directory in installed:
        if package_directory == directory:
            continue
        records.append(
            classify_package(
                ecosystem="npm",
                name=name,
                version=version,
                license_value=license_value,
                policy=policy,
            )
        )
    installed_names = {normalized_name(record["name"]) for record in records}
    declared = {
        **(manifest.get("dependencies") or {}),
        **(manifest.get("devDependencies") or {}),
    }
    for name in declared:
        if normalized_name(name) not in installed_names:
            records.append(
                {
                    "ecosystem": "npm",
                    "name": str(name),
                    "version": "missing",
                    "declared_license": None,
                    "license": "UNKNOWN",
                    "status": "blocked",
                    "reason": "Declared dependency is not installed; dependency scan would be incomplete",
                }
            )
    return dedupe(records)


# ---------------------------------------------------------------------------
# Rust crates
# ---------------------------------------------------------------------------


def scan_cargo(manifest_path: Path, policy: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise ScanError(f"Missing Cargo manifest: {manifest_path}")
    cargo = shutil.which("cargo")
    if not cargo:
        raise ScanError("cargo is not installed; install Rust to scan resolved crates")
    command = [cargo, "metadata", "--format-version", "1", "--manifest-path", str(manifest_path)]
    if (manifest_path.parent / "Cargo.lock").is_file():
        command.append("--locked")
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScanError(f"cargo metadata failed: {exc}") from exc
    if completed.returncode:
        raise ScanError(f"cargo metadata failed: {completed.stderr.strip()[:2000]}")
    try:
        data = json.loads(completed.stdout)
    except ValueError as exc:
        raise ScanError(f"cargo metadata returned invalid JSON: {exc}") from exc
    workspace_members = set(data.get("workspace_members", []))
    records = []
    for package in data.get("packages", []):
        if not isinstance(package, dict) or package.get("id") in workspace_members:
            continue
        name = str(package.get("name") or "unknown")
        version = str(package.get("version") or "unknown")
        license_value = package.get("license")
        if not license_value and package.get("license_file"):
            try:
                license_path = Path(package.get("manifest_path", "")).parent / str(package["license_file"])
                license_value = infer_license(license_path.read_text(encoding="utf-8", errors="replace")[:16000])
            except OSError:
                license_value = None
        if not license_value:
            try:
                license_value = _infer_license_from_files(Path(package.get("manifest_path", "")).parent)
            except OSError:
                license_value = None
        records.append(
            classify_package(
                ecosystem="cargo",
                name=name,
                version=version,
                license_value=str(license_value) if license_value else None,
                policy=policy,
            )
        )
    return dedupe(records)


# ---------------------------------------------------------------------------
# Vendored source and repository license
# ---------------------------------------------------------------------------


def scan_vendored(root: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    allowed = {normalize_license(item) or item for item in policy.get("allowed_licenses", [])}
    declared_roots = set()
    for entry in policy.get("vendored", []):
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        relative = Path(str(entry["path"]))
        declared_roots.add(relative.as_posix())
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            records.append(
                {
                    "ecosystem": "vendored",
                    "name": relative.as_posix(),
                    "version": str(entry.get("version", "unknown")),
                    "declared_license": entry.get("license"),
                    "license": "UNKNOWN",
                    "status": "blocked",
                    "reason": "Vendored path escapes the repository root",
                }
            )
            continue
        if not path.is_dir():
            records.append(
                {
                    "ecosystem": "vendored",
                    "name": relative.as_posix(),
                    "version": str(entry.get("version", "unknown")),
                    "declared_license": entry.get("license"),
                    "license": "UNKNOWN",
                    "status": "blocked",
                    "reason": "Declared vendored tree is missing",
                }
            )
            continue
        license_file = root / str(entry.get("license_file", ""))
        detected = None
        if license_file.is_file():
            try:
                detected = normalize_license(license_file.read_text(encoding="utf-8", errors="replace")[:16000])
            except OSError:
                detected = None
        declared = str(entry.get("license") or "")
        provenance = root / str(entry.get("provenance_file", ""))
        ok = (
            detected == declared
            and declared in allowed
            and (not entry.get("provenance_file") or provenance.is_file())
        )
        records.append(
            {
                "ecosystem": "vendored",
                "name": relative.as_posix(),
                "version": str(entry.get("version", "unknown")),
                "declared_license": declared,
                "license": detected or "UNKNOWN",
                "status": "approved" if ok else "blocked",
                "reason": "Vendored license and provenance verified"
                if ok
                else "Missing or mismatched license/provenance file",
            }
        )
    third_party = root / "third_party"
    if third_party.is_dir():
        for child in sorted(third_party.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            relative = child.relative_to(root).as_posix()
            if relative not in declared_roots:
                records.append(
                    {
                        "ecosystem": "vendored",
                        "name": relative,
                        "version": "unknown",
                        "declared_license": None,
                        "license": "UNKNOWN",
                        "status": "blocked",
                        "reason": "Vendored directory is not approved in security/license-policy.json",
                    }
                )
    root_license = root / "LICENSE"
    detected_root = None
    if root_license.is_file():
        try:
            detected_root = normalize_license(root_license.read_text(encoding="utf-8", errors="replace")[:16000])
        except OSError:
            detected_root = None
    records.append(
        {
            "ecosystem": "repository",
            "name": "first-party-source",
            "version": "workspace",
            "declared_license": "MIT",
            "license": detected_root or "UNKNOWN",
            "status": "approved" if detected_root == "MIT" else "blocked",
            "reason": "First-party source is MIT licensed"
            if detected_root == "MIT"
            else "First-party LICENSE is missing or is not MIT",
        }
    )
    return dedupe(records)


# ---------------------------------------------------------------------------
# Model registry and distribution manifest
# ---------------------------------------------------------------------------


def scan_models(
    root: Path, model_policy_path: Path, manifest_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    policy = load_json(model_policy_path)
    errors = validate_model_policy(policy)
    records = []
    if errors:
        for error in errors:
            records.append(
                {
                    "ecosystem": "model-policy",
                    "name": "model-registry",
                    "version": "unvalidated",
                    "declared_license": None,
                    "license": "UNKNOWN",
                    "status": "blocked",
                    "reason": error,
                }
            )
        return records, None
    allowed = set(policy.get("allowed_license_ids", []))
    custom = policy.get("custom_licenses", {}) or {}
    for model in policy.get("models", []):
        license_id = str(model.get("license", ""))
        if license_id in custom:
            status = "conditional"
            reason = f"Custom license reviewed: {custom[license_id].get('summary', '')}"
        elif license_id in allowed:
            status = "approved"
            reason = "Model license is on the allowlist"
        else:
            status = "blocked"
            reason = "Model license is not approved"
        records.append(
            {
                "ecosystem": "model",
                "name": str(model.get("id", "unknown")),
                "version": "reviewed",
                "declared_license": license_id,
                "license": license_id,
                "status": status,
                "reason": reason,
            }
        )
    manifest_result = None
    if manifest_path.is_file():
        manifest_result = check_model_manifest(load_json(manifest_path), policy)
        for decision in manifest_result["decisions"]:
            records.append(
                {
                    "ecosystem": "model-distribution",
                    "name": str(decision.get("model_id", "unknown")),
                    "version": "bundled",
                    "declared_license": decision.get("license"),
                    "license": decision.get("license") or "UNKNOWN",
                    "status": "approved" if decision["approved"] else decision.get("status", "blocked"),
                    "reason": decision.get("reason", ""),
                }
            )
    return dedupe(records), manifest_result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(ROOT), help="Repository root")
    parser.add_argument("--policy", help="Dependency license policy JSON")
    parser.add_argument("--model-policy", help="Model license registry JSON")
    parser.add_argument("--model-manifest", help="Bundled-model distribution JSON")
    parser.add_argument("--python", action="store_true", help="Scan installed Python distributions")
    parser.add_argument("--requirements", action="store_true", help="Scan declared Python requirements")
    parser.add_argument("--vendored", action="store_true", help="Scan vendored source trees")
    parser.add_argument("--models", action="store_true", help="Validate model registry and distribution manifest")
    parser.add_argument("--node", action="append", default=[], metavar="DIR", help="Node project directory")
    parser.add_argument("--cargo", action="append", default=[], metavar="MANIFEST", help="Cargo.toml to resolve")
    parser.add_argument("--all", action="store_true", help="Enable every scan and discover local manifests")
    parser.add_argument("--report", metavar="PATH", help="Write the full JSON report")
    parser.add_argument("--quiet", action="store_true", help="Only print failures and the final result")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    policy_path = Path(args.policy).resolve() if args.policy else root / "security" / "license-policy.json"
    model_policy_path = (
        Path(args.model_policy).resolve()
        if args.model_policy
        else root / "security" / "model-policy.json"
    )
    model_manifest_path = (
        Path(args.model_manifest).resolve()
        if args.model_manifest
        else root / "security" / "model-distribution.json"
    )

    selected = any(
        [args.python, args.requirements, args.vendored, args.models, args.node, args.cargo, args.all]
    )
    if not selected:
        args.requirements = args.vendored = args.models = True
    if args.all:
        args.python = args.requirements = args.vendored = args.models = True
        for manifest in sorted(root.glob("apps/*/package.json")):
            args.node.append(str(manifest.parent))
        for manifest in sorted(root.glob("packages/*/package.json")):
            args.node.append(str(manifest.parent))
        for manifest in sorted(root.glob("services/*/Cargo.toml")):
            args.cargo.append(str(manifest))

    try:
        policy = load_json(policy_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"LICENSE SCAN ERROR: cannot load policy {policy_path}: {exc}", file=sys.stderr)
        return 2

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    model_manifest_result = None

    def run(label: str, callback) -> None:
        try:
            found = callback()
            if found is not None:
                records.extend(found)
        except (ScanError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{label}: {exc}")

    if args.python:
        run("python", lambda: scan_installed_python(policy))
    if args.requirements:
        run("requirements", lambda: scan_declared_python(root, policy))
    if args.vendored:
        run("vendored", lambda: scan_vendored(root, policy))
    if args.models:
        try:
            found, model_manifest_result = scan_models(root, model_policy_path, model_manifest_path)
            records.extend(found)
        except (ScanError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"models: {exc}")
    for directory in dict.fromkeys(args.node):
        run(f"node:{directory}", lambda directory=directory: scan_node(Path(directory), policy))
    for manifest in dict.fromkeys(args.cargo):
        run(f"cargo:{manifest}", lambda manifest=manifest: scan_cargo(Path(manifest), policy, root))

    records = dedupe(records)
    violations = [record for record in records if record["status"] in ("blocked", "unknown")]
    summary = {
        "total": len(records),
        "approved": sum(record["status"] == "approved" for record in records),
        "conditional": sum(record["status"] == "conditional" for record in records),
        "blocked": sum(record["status"] == "blocked" for record in records),
        "unknown": sum(record["status"] == "unknown" for record in records),
        "scan_errors": len(errors),
    }
    passed = not violations and not errors
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "root": str(root),
        "policy": str(policy_path),
        "passed": passed,
        "summary": summary,
        "packages": sorted(
            records, key=lambda item: (item["ecosystem"], item["name"].lower(), item["version"])
        ),
        "violations": violations,
        "scan_errors": errors,
        "model_distribution": model_manifest_result,
    }
    if args.report:
        destination = Path(args.report)
        if not destination.is_absolute():
            destination = root / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        print(
            "License scan: "
            f"{summary['total']} records · {summary['approved']} approved · "
            f"{summary['conditional']} conditional · {summary['blocked']} blocked · "
            f"{summary['unknown']} unknown · {len(errors)} scan error(s)"
        )
    for violation in violations:
        print(
            f"BLOCKED [{violation['ecosystem']}] {violation['name']}@{violation['version']} "
            f"({violation['license']}): {violation['reason']}",
            file=sys.stderr,
        )
    for error in errors:
        print(f"SCAN ERROR: {error}", file=sys.stderr)
    if model_manifest_result is not None:
        print(
            ("Model distribution: " if model_manifest_result["approved"] else "Model distribution BLOCKED: ")
            + model_manifest_result["reason"]
        )
    print("PASS: every scanned dependency, vendored tree, and model is approved." if passed else "FAILED: license policy violations or incomplete scans.")
    return 0 if passed else (2 if errors and not violations else 1)


if __name__ == "__main__":
    raise SystemExit(main())
