"""Validate the third-party registry and its license obligations.

Run in CI or locally:

    python scripts/check_oss_licenses.py

Checks performed:
* registry schema (name, GitHub URL, SPDX license, usage, pin)
* every bundled component uses an allowlisted permissive license
* vendored components ship an existing notice file with license text
* copyleft components are marked not bundled and explain their isolation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "third_party" / "oss_registry.json"
USAGES = {"vendored", "submodule", "dependency", "dev-dependency",
          "optional-runtime", "reference"}
COPYLEFT = ("GPL", "AGPL", "LGPL", "SSPL", "EUPL")
LICENSE_MARKERS = {
    "MIT": "permission is hereby granted",
    "Apache-2.0": "apache license",
    "BSD-2-Clause": "redistribution and use in source and binary forms",
    "BSD-3-Clause": "redistribution and use in source and binary forms",
    "ISC": "permission to use, copy, modify",
    "MPL-2.0": "mozilla public license",
}


def load(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(root: Path = ROOT) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    registry = load(root / "third_party" / "oss_registry.json")
    allowed = set(registry.get("allowed_spdx", []))
    entries = registry.get("repositories")
    if not isinstance(entries, list) or not entries:
        return {"errors": ["registry has no repositories"], "warnings": [], "count": 0,
                "allowed_spdx": sorted(allowed), "names": []}

    seen: set[str] = set()
    names: list[str] = []
    for index, entry in enumerate(entries):
        label = entry.get("name") or f"entry[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: entry is not an object")
            continue
        if label in seen:
            errors.append(f"{label}: duplicate name")
        seen.add(label)
        names.append(label)
        repo = str(entry.get("repo", ""))
        if not repo.startswith("https://github.com/"):
            errors.append(f"{label}: repo must be an https://github.com/ URL")
        license_name = str(entry.get("license", ""))
        if not license_name:
            errors.append(f"{label}: missing SPDX license")
        usage = entry.get("usage")
        if usage not in USAGES:
            errors.append(f"{label}: unknown usage {usage!r}")
        if not str(entry.get("pin", "")).strip():
            errors.append(f"{label}: missing version or pin")
        bundled = bool(entry.get("bundled"))
        if usage in ("vendored", "submodule") and not bundled and "bundled" not in entry:
            errors.append(f"{label}: bundled flag must be explicit for {usage} components")
        copyleft = any(license_name.upper().startswith(prefix) for prefix in COPYLEFT)
        if copyleft:
            if bundled:
                errors.append(f"{label}: copyleft component must not be bundled")
            if not str(entry.get("isolation", "")).strip():
                errors.append(f"{label}: copyleft component needs an isolation explanation")
            warnings.append(f"{label}: copyleft ({license_name}); independent review required")
        elif bundled and license_name not in allowed:
            errors.append(f"{label}: bundled license {license_name} is not allowlisted")
        notice = entry.get("notice")
        if usage == "vendored":
            if not notice:
                errors.append(f"{label}: vendored components require a notice path")
            else:
                notice_path = root / notice
                if not notice_path.is_file():
                    errors.append(f"{label}: notice file missing: {notice}")
                elif notice_path.stat().st_size == 0:
                    errors.append(f"{label}: notice file is empty: {notice}")
                else:
                    text = notice_path.read_text(encoding="utf-8", errors="replace").lower()
                    marker = LICENSE_MARKERS.get(license_name)
                    if marker and marker not in text:
                        errors.append(f"{label}: notice does not look like {license_name}: {notice}")
        if usage == "submodule":
            modules = (root / ".gitmodules")
            if not modules.is_file():
                errors.append(f"{label}: submodule entry but .gitmodules is missing")
            else:
                declared = modules.read_text(encoding="utf-8", errors="replace")
                if "upstream/" not in declared:
                    errors.append(f"{label}: submodule path is not declared in .gitmodules")

    if not any(entry.get("usage") == "vendored" for entry in entries if isinstance(entry, dict)):
        warnings.append("no vendored components registered")
    return {
        "errors": errors,
        "warnings": warnings,
        "count": len(names),
        "allowed_spdx": sorted(allowed),
        "names": names,
    }


def main() -> int:
    report = validate()
    for label in ("errors", "warnings"):
        for message in report[label]:
            print(f"{label[:-1].upper()}: {message}")
    print(f"{report['count']} third-party entries checked; "
          f"{len(report['errors'])} errors, {len(report['warnings'])} warnings")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
