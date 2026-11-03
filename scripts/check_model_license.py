#!/usr/bin/env python3
"""Fail-closed model license checks.

Examples:
    python scripts/check_model_license.py --list
    python scripts/check_model_license.py --validate
    python scripts/check_model_license.py --model Qwen/Qwen2.5-Coder-7B-Instruct \
        --license Apache-2.0 --use training
    python scripts/check_model_license.py --manifest security/model-distribution.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.licensing.policy import (  # noqa: E402
    DEFAULT_MODEL_MANIFEST,
    DEFAULT_MODEL_POLICY,
    USES,
    check_model,
    check_model_manifest,
    load_json,
    validate_model_policy,
)


def print_decision(decision: dict) -> None:
    mark = "APPROVED" if decision["approved"] else "DENIED"
    print(f"{mark}: {decision.get('model_id')} [{decision.get('use')}]")
    print(f"  license: {decision.get('license')}")
    print(f"  reason:  {decision.get('reason')}")
    for requirement in decision.get("requirements", []):
        print(f"  obligation: {requirement}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--policy", default=str(DEFAULT_MODEL_POLICY), help="Reviewed model registry")
    parser.add_argument("--manifest", help="Distribution manifest of bundled model weights")
    parser.add_argument("--validate", action="store_true", help="Validate the registry itself")
    parser.add_argument("--list", action="store_true", help="List reviewed models and permitted uses")
    parser.add_argument("--model", help="Exact model id or registered alias")
    parser.add_argument("--license", help="License identifier from the provider")
    parser.add_argument("--use", choices=USES, default="inference", help="Intended use")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        policy = load_json(args.policy)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"MODEL POLICY ERROR: cannot load {args.policy}: {exc}", file=sys.stderr)
        return 2

    registry_errors = validate_model_policy(policy)
    if registry_errors:
        print("MODEL POLICY INVALID", file=sys.stderr)
        for error in registry_errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    if args.validate:
        print(f"Model policy valid: {len(policy['models'])} reviewed model(s).")
        return 0

    if args.list:
        if args.json:
            print(json.dumps(policy["models"], indent=2))
            return 0
        print(f"{'MODEL':52} {'LICENSE':24} {'INFER':5} {'TRAIN':5} {'REDIST':6} {'SHIP':5}")
        for model in policy["models"]:
            uses = model.get("uses", {})
            flags = ["yes" if uses.get(use) else "no" for use in USES]
            print(f"{model['id']:52} {model['license']:24} {flags[0]:5} {flags[1]:5} {flags[2]:6} {flags[3]:5}")
        return 0

    if args.manifest:
        try:
            manifest = load_json(args.manifest)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"MODEL MANIFEST ERROR: {exc}", file=sys.stderr)
            return 2
        result = check_model_manifest(manifest, policy)
        for decision in result["decisions"]:
            print_decision(decision)
        if args.json:
            print(json.dumps(result, indent=2))
        print(("PASS: " if result["approved"] else "BLOCKED: ") + result["reason"])
        return 0 if result["approved"] else 1

    if args.model:
        if not args.license:
            parser.error("--license is required with --model; use the exact provider license")
        decision = check_model(args.model, args.license, args.use, policy)
        if args.json:
            print(json.dumps(decision, indent=2))
        else:
            print_decision(decision)
        return 0 if decision["approved"] else 1

    parser.error("choose --validate, --list, --model, or --manifest")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
