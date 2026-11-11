"""Fail-closed license policy shared by scripts, tests, and the training gate.

Dependency policy is intentionally allowlist-based: a license must be named in
``security/license-policy.json`` or the package fails the scan. Model policy is
model-specific because several capable coding models use custom community
licenses that are not OSI-approved and cannot be approved by license name alone.
"""

from __future__ import annotations

import datetime as _datetime
import fnmatch
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LICENSE_POLICY = ROOT / "security" / "license-policy.json"
DEFAULT_MODEL_POLICY = ROOT / "security" / "model-policy.json"
DEFAULT_MODEL_MANIFEST = ROOT / "security" / "model-distribution.json"

USES = ("inference", "training", "redistribution", "shipping")
STATUSES = ("approved", "conditional", "blocked", "unknown")

# Metadata often reports a human name instead of an SPDX identifier. Keep this
# list explicit; an unrecognised string must fail closed, never pass by default.
_ALIASES = {
    "mit": "MIT",
    "mit license": "MIT",
    "the mit license": "MIT",
    "expat": "MIT",
    "mit-0": "MIT-0",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "asl 2.0": "Apache-2.0",
    "bsd": "BSD-3-Clause",
    "bsd license": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd 2-clause": "BSD-2-Clause",
    "simplified bsd": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "new bsd": "BSD-3-Clause",
    "modified bsd": "BSD-3-Clause",
    "0bsd": "0BSD",
    "bsd zero clause": "0BSD",
    "isc": "ISC",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "mpl-2.0": "MPL-2.0",
    "mozilla public license 2.0": "MPL-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python-2.0": "Python-2.0",
    "python software foundation license": "PSF-2.0",
    "psf-2.0": "PSF-2.0",
    "unlicense": "Unlicense",
    "the unlicense": "Unlicense",
    "the unlicense (unlicense)": "Unlicense",
    "wtfpl": "WTFPL",
    "zlib": "Zlib",
    "zlib license": "Zlib",
    "boost software license 1.0": "BSL-1.0",
    "bsl-1.0": "BSL-1.0",
    "blueoak-1.0.0": "BlueOak-1.0.0",
    "blue oak model license 1.0.0": "BlueOak-1.0.0",
    "cc0-1.0": "CC0-1.0",
    "creative commons zero v1.0 universal": "CC0-1.0",
    "openssl": "OpenSSL",
    "unicode-dfs-2016": "Unicode-DFS-2016",
    "unicode-3.0": "Unicode-3.0",
    "gpl-2.0": "GPL-2.0",
    "gpl-2.0-only": "GPL-2.0",
    "gpl-2.0-or-later": "GPL-2.0",
    "gplv2": "GPL-2.0",
    "gnu general public license v2 (gplv2)": "GPL-2.0",
    "gpl-3.0": "GPL-3.0",
    "gpl-3.0-only": "GPL-3.0",
    "gpl-3.0-or-later": "GPL-3.0",
    "gplv3": "GPL-3.0",
    "gnu general public license v3 (gplv3)": "GPL-3.0",
    "lgpl-2.1": "LGPL-2.1",
    "lgpl-3.0": "LGPL-3.0",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0",
    "agpl-3.0": "AGPL-3.0",
    "gnu affero general public license v3": "AGPL-3.0",
    "sspl-1.0": "SSPL-1.0",
    "server side public license": "SSPL-1.0",
    "busl-1.1": "BUSL-1.1",
    "business source license 1.1": "BUSL-1.1",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "creative commons attribution non commercial 4.0": "CC-BY-NC-4.0",
    "json": "JSON",
    "unknown": "UNKNOWN",
}

_CLASSIFIER_ALIASES = {
    "mit license": "MIT",
    "apache software license": "Apache-2.0",
    "bsd license": "BSD-3-Clause",
    "isc license (iscl)": "ISC",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python software foundation license": "PSF-2.0",
    "the unlicense (unlicense)": "Unlicense",
    "gnu general public license v2 (gplv2)": "GPL-2.0",
    "gnu general public license v3 (gplv3)": "GPL-3.0",
    "gnu lesser general public license v2 (lgplv2)": "LGPL-2.1",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0",
    "gnu affero general public license v3": "AGPL-3.0",
    "creative commons attribution non commercial 4.0 international": "CC-BY-NC-4.0",
}

_TEXT_SIGNATURES = (
    ("permission is hereby granted, free of charge", "MIT"),
    ("apache license", "Apache-2.0"),
    ("mozilla public license", "MPL-2.0"),
    ("gnu affero general public license", "AGPL-3.0"),
    ("gnu lesser general public license", "LGPL-3.0"),
    ("gnu general public license", "GPL-3.0"),
    ("python software foundation license", "PSF-2.0"),
    ("redistribution and use in source and binary forms", "BSD-3-Clause"),
    ("isc license", "ISC"),
    ("the unlicense", "Unlicense"),
    ("server side public license", "SSPL-1.0"),
    ("business source license", "BUSL-1.1"),
    ("creative commons attribution-noncommercial", "CC-BY-NC-4.0"),
    ("blue oak model license", "BlueOak-1.0.0"),
    ("boost software license", "BSL-1.0"),
    ("unicode, inc. license", "Unicode-DFS-2016"),
    ("unicode license agreement", "Unicode-3.0"),
)

_KNOWN_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")


class ModelLicenseError(RuntimeError):
    """Raised when a model is not approved for the requested use."""


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def infer_license(text: str | None) -> str | None:
    """Best-effort detection of a license from a full license text."""
    if not text:
        return None
    lowered = re.sub(r"\s+", " ", str(text)).lower()
    for signature, identifier in _TEXT_SIGNATURES:
        if signature in lowered:
            if identifier == "Apache-2.0" and "2.0" not in lowered:
                continue
            if identifier == "GPL-3.0" and "version 3" not in lowered and "v3" not in lowered:
                continue
            if identifier == "LGPL-3.0" and "version 3" not in lowered and "v3" not in lowered:
                continue
            if identifier == "MPL-2.0" and "2.0" not in lowered:
                continue
            return identifier
    return None


def normalize_license(value: str | None) -> str | None:
    """Normalize a single license identifier or human-readable name.

    Unknown values are returned only when they look like a single token so the
    evaluator can report them as blocked. Free-form license prose becomes the
    detected identifier, or ``None``.
    """
    if value is None:
        return None
    cleaned = " ".join(str(value).replace("\u00a0", " ").split()).strip().strip(".,;")
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in _ALIASES:
        return _ALIASES[lowered]
    if len(cleaned) <= 80 and _KNOWN_TOKEN.fullmatch(cleaned):
        return cleaned
    detected = infer_license(cleaned)
    if detected:
        return detected
    # "MIT/Apache-2.0" and similar dual-license shorthand.
    if "/" in cleaned:
        parts = [normalize_license(part) for part in cleaned.split("/") if part.strip()]
        if parts and all(parts):
            return " OR ".join(parts)
    return None


def normalize_expression(value: str | None) -> str | None:
    """Return a cleaned SPDX-style expression, or ``None`` for free-form prose."""
    if value is None:
        return None
    cleaned = " ".join(str(value).replace("\u00a0", " ").split()).strip().strip(".,;")
    if not cleaned or len(cleaned) > 200:
        return None
    prepared = re.sub(r"\s*/\s*", " OR ", cleaned)
    try:
        _ExpressionParser(prepared).parse()
    except (ValueError, IndexError):
        return None
    return prepared


def normalize_metadata_license(
    license_value: str | None, classifiers: Iterable[str] = ()
) -> str | None:
    """Resolve Python package metadata, preferring an SPDX expression."""
    expression = normalize_expression(license_value)
    if expression and expression.upper() != "UNKNOWN":
        return expression
    direct = normalize_license(license_value)
    if direct and direct != "UNKNOWN":
        return direct
    mapped = []
    for classifier in classifiers or ():
        if not isinstance(classifier, str) or "License ::" not in classifier:
            continue
        tail = classifier.split("::")[-1].strip().lower()
        if tail in ("osi approved", "other/proprietary license"):
            continue
        if tail in _CLASSIFIER_ALIASES:
            mapped.append(_CLASSIFIER_ALIASES[tail])
    if mapped:
        unique = list(dict.fromkeys(mapped))
        return " OR ".join(unique)
    return direct


def _tokenize(expression: str) -> list[str]:
    prepared = re.sub(r"\s*/\s*", " OR ", expression)
    tokens = re.findall(r"\(|\)|\bAND\b|\bOR\b|\bWITH\b|[^\s()]+", prepared, flags=re.IGNORECASE)
    return [token if token in ("(", ")") else token for token in tokens]


class _ExpressionParser:
    def __init__(self, expression: str):
        self.tokens = _tokenize(expression)
        self.position = 0

    def parse(self) -> tuple:
        node = self._parse_or()
        if self.position != len(self.tokens):
            raise ValueError("Unexpected token in license expression")
        return node

    def _peek(self) -> str | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise ValueError("Unexpected end of license expression")
        self.position += 1
        return token

    def _parse_or(self) -> tuple:
        node = self._parse_and()
        while (self._peek() or "").upper() == "OR":
            self._take()
            node = ("OR", node, self._parse_and())
        return node

    def _parse_and(self) -> tuple:
        node = self._parse_atom()
        while (self._peek() or "").upper() == "AND":
            self._take()
            node = ("AND", node, self._parse_atom())
        return node

    def _parse_atom(self) -> tuple:
        token = self._take()
        if token == "(":
            node = self._parse_or()
            if self._take() != ")":
                raise ValueError("Unbalanced parentheses")
            return node
        if token in (")",):
            raise ValueError("Unexpected closing parenthesis")
        if (self._peek() or "").upper() == "WITH":
            self._take()
            exception = self._take()
            return ("WITH", token, exception)
        return ("LICENSE", token)


def _allowed_license(identifier: str, policy: Mapping[str, Any]) -> tuple[bool, str, str]:
    canonical = normalize_license(identifier) or identifier
    allowed = {normalize_license(item) or item for item in policy.get("allowed_licenses", [])}
    conditional = {
        normalize_license(item) or item: note
        for item, note in (policy.get("conditional_licenses") or {}).items()
    }
    expressions = set(policy.get("allowed_license_expressions", [])) | {
        normalize_license(item) or item
        for item in policy.get("allowed_license_expressions", [])
    }
    blocked = {normalize_license(item) or item for item in policy.get("blocked_licenses", [])}
    if identifier in expressions or canonical in expressions:
        return True, "approved", f"{identifier} is explicitly approved"
    if canonical in allowed:
        return True, "approved", f"{canonical} is on the allowlist"
    if canonical in conditional:
        return True, "conditional", str(conditional[canonical])
    if canonical in blocked:
        return False, "blocked", f"{canonical} is on the blocked list"
    return False, "blocked", f"{canonical} is not an approved license"


def evaluate_license(
    expression: str | None, policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate an SPDX-style expression against the dependency allowlist.

    ``OR`` passes when at least one branch passes (the recipient may choose it).
    ``AND`` requires every branch. Unknown or unparseable expressions fail.
    """
    if not expression:
        return {
            "approved": False,
            "status": "unknown",
            "reason": "No license metadata was declared",
            "licenses": [],
        }
    try:
        tree = _ExpressionParser(str(expression)).parse()
    except (ValueError, IndexError) as exc:
        return {
            "approved": False,
            "status": "unknown",
            "reason": f"Unparseable license expression: {exc}",
            "licenses": [],
        }

    components: list[dict[str, str]] = []

    def visit(node: tuple) -> tuple[bool, str, str]:
        kind = node[0]
        if kind == "LICENSE":
            canonical = normalize_license(node[1])
            if not canonical:
                components.append({"license": node[1], "status": "unknown"})
                return False, "unknown", f"{node[1]} is not a recognised license"
            approved, status, reason = _allowed_license(canonical, policy)
            components.append({"license": canonical, "status": status})
            return approved, status, reason
        if kind == "WITH":
            base, exception = node[1], node[2]
            raw_combined = f"{base} WITH {exception}"
            combined = f"{normalize_license(base) or base} WITH {exception}"
            allowed_expressions = set(policy.get("allowed_license_expressions", [])) | {
                normalize_license(item) or item
                for item in policy.get("allowed_license_expressions", [])
            }
            allowed_exceptions = set(policy.get("allowed_exceptions", []))
            if raw_combined in allowed_expressions or combined in allowed_expressions:
                components.append({"license": raw_combined, "status": "approved"})
                return True, "approved", f"{raw_combined} is explicitly approved"
            base_ok, base_status, base_reason = _allowed_license(base, policy)
            if base_ok and exception in allowed_exceptions:
                components.append({"license": combined, "status": "approved"})
                return True, "approved", f"{exception} is an approved exception"
            components.append({"license": combined, "status": base_status})
            return False, base_status, base_reason
        left = visit(node[1])
        right = visit(node[2])
        if kind == "OR":
            if left[0] or right[0]:
                status = "approved" if "approved" in (left[1], right[1]) else "conditional"
                return True, status, "At least one alternative is approved"
            status = "blocked" if "blocked" in (left[1], right[1]) else "unknown"
            return False, status, "No alternative is approved"
        if kind == "AND":
            if left[0] and right[0]:
                status = "conditional" if "conditional" in (left[1], right[1]) else "approved"
                return True, status, "Every required license is approved"
            status = "blocked" if "blocked" in (left[1], right[1]) else "unknown"
            return False, status, "A required license is not approved"
        return False, "unknown", "Invalid license expression"

    approved, status, reason = visit(tree)
    return {
        "approved": approved,
        "status": status if status in STATUSES else "unknown",
        "reason": reason,
        "licenses": components,
    }


def _find_exception(
    policy: Mapping[str, Any], ecosystem: str, name: str, version: str, license_value: str | None
) -> Mapping[str, Any] | None:
    for exception in policy.get("exceptions", []):
        if not isinstance(exception, dict):
            continue
        if exception.get("ecosystem") != ecosystem or exception.get("name") != name:
            continue
        pattern = str(exception.get("version", "*"))
        if not fnmatch.fnmatchcase(version or "", pattern):
            continue
        declared = exception.get("license")
        if declared:
            declared_norm = normalize_license(str(declared))
            actual_norm = normalize_license(str(license_value) if license_value else "")
            if declared_norm and actual_norm and declared_norm != actual_norm:
                continue
            if not declared_norm and " WITH " in str(declared):
                base = str(declared).split(" WITH ", 1)[0]
                if actual_norm and normalize_license(base) != actual_norm:
                    continue
        return exception
    return None


def classify_package(
    *, ecosystem: str, name: str, version: str, license_value: str | None,
    policy: Mapping[str, Any], classifiers: Iterable[str] = ()
) -> dict[str, Any]:
    """Return a report-ready verdict for one dependency instance."""
    first_party = policy.get("first_party", {})
    known_first_party = {
        item.lower()
        for item in (
            list(first_party.get("python_distributions", []))
            + list(first_party.get("node_packages", []))
            + list(first_party.get("rust_packages", []))
        )
    }
    if name.lower() in known_first_party:
        return {
            "ecosystem": ecosystem,
            "name": name,
            "version": version,
            "declared_license": license_value,
            "license": "MIT",
            "status": "approved",
            "reason": "First-party package covered by the repository MIT license",
        }

    exception = _find_exception(policy, ecosystem, name, version, license_value)
    if exception:
        return {
            "ecosystem": ecosystem,
            "name": name,
            "version": version,
            "declared_license": license_value,
            "license": exception.get("license") or license_value or "UNKNOWN",
            "status": "approved",
            "reason": f"Policy exception: {exception.get('reason', 'approved')}",
        }

    if ecosystem == "python":
        expression = normalize_metadata_license(license_value, classifiers)
    else:
        expression = normalize_expression(license_value) or normalize_license(license_value)
    verdict = evaluate_license(expression, policy)
    return {
        "ecosystem": ecosystem,
        "name": name,
        "version": version,
        "declared_license": license_value,
        "license": expression or "UNKNOWN",
        "status": verdict["status"],
        "reason": verdict["reason"],
    }


def _match_model(model_id: str, policy: Mapping[str, Any]) -> Mapping[str, Any] | None:
    wanted = model_id.strip().lower()
    for model in policy.get("models", []):
        names = [str(model.get("id", ""))] + [str(alias) for alias in model.get("aliases", [])]
        if any(name.strip().lower() == wanted for name in names):
            return model
    return None


def check_model(
    model_id: str,
    license_id: str,
    use: str,
    policy: Mapping[str, Any] | None = None,
    *,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    """Check a model's registered license for one concrete use.

    Returns a decision dict with ``approved``, ``status``, ``reason``,
    ``requirements`` and the matched model record. Unknown models and license
    mismatches fail closed.
    """
    if policy is None:
        policy = load_json(policy_path or DEFAULT_MODEL_POLICY)
    if use not in USES:
        raise ValueError(f"Unknown model use: {use}")
    model = _match_model(model_id, policy)
    if not model:
        return {
            "approved": False,
            "status": "unapproved",
            "use": use,
            "model_id": model_id,
            "license": license_id,
            "reason": "Model is not in the reviewed registry. Add it to security/model-policy.json after license review.",
            "requirements": [],
        }
    registered_license = str(model.get("license", ""))
    if not license_id or normalize_license(license_id) != normalize_license(registered_license):
        return {
            "approved": False,
            "status": "mismatch",
            "use": use,
            "model_id": model.get("id"),
            "license": license_id,
            "reason": f"Supplied license does not match the reviewed value ({registered_license})",
            "requirements": list(model.get("requirements", [])),
        }
    custom = policy.get("custom_licenses", {}).get(registered_license)
    if custom is None and registered_license not in policy.get("allowed_license_ids", []):
        return {
            "approved": False,
            "status": "unapproved",
            "use": use,
            "model_id": model.get("id"),
            "license": registered_license,
            "reason": "License is neither on the model allowlist nor explicitly reviewed as a custom license",
            "requirements": list(model.get("requirements", [])),
        }
    if custom is not None and not custom.get("reviewed"):
        return {
            "approved": False,
            "status": "unapproved",
            "use": use,
            "model_id": model.get("id"),
            "license": registered_license,
            "reason": "Custom model license has not been reviewed",
            "requirements": list(model.get("requirements", [])),
        }
    uses = model.get("uses") or {}
    if uses.get(use) is not True:
        return {
            "approved": False,
            "status": "restricted",
            "use": use,
            "model_id": model.get("id"),
            "license": registered_license,
            "reason": f"The reviewed license does not permit '{use}' in this project",
            "requirements": list(model.get("requirements", [])),
        }
    return {
        "approved": True,
        "status": "approved",
        "use": use,
        "model_id": model.get("id"),
        "license": registered_license,
        "license_url": model.get("license_url"),
        "reason": "Model and license are approved for this use",
        "requirements": list(model.get("requirements", [])),
    }


def require_model_use(
    model_id: str,
    license_id: str,
    use: str,
    policy: Mapping[str, Any] | None = None,
    *,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    decision = check_model(model_id, license_id, use, policy, policy_path=policy_path)
    if not decision["approved"]:
        raise ModelLicenseError(decision["reason"])
    return decision


def validate_model_policy(policy: Mapping[str, Any]) -> list[str]:
    """Validate the registry itself. Any error must block CI and releases."""
    errors: list[str] = []
    if policy.get("version") != 1:
        errors.append("version must be 1")
    allowed = policy.get("allowed_license_ids")
    if not isinstance(allowed, list) or not allowed:
        errors.append("allowed_license_ids must be a non-empty list")
        allowed = []
    custom = policy.get("custom_licenses")
    if not isinstance(custom, dict):
        errors.append("custom_licenses must be an object")
        custom = {}
    for name, details in custom.items():
        if not isinstance(details, dict):
            errors.append(f"custom_licenses.{name} must be an object")
            continue
        if details.get("reviewed") is not True:
            errors.append(f"custom_licenses.{name} must be reviewed")
        url = str(details.get("license_url", ""))
        if not url.startswith("https://"):
            errors.append(f"custom_licenses.{name}.license_url must be HTTPS")
        if not str(details.get("summary", "")).strip():
            errors.append(f"custom_licenses.{name}.summary is required")
    models = policy.get("models")
    if not isinstance(models, list) or not models:
        errors.append("models must be a non-empty list")
        models = []
    seen_ids: set[str] = set()
    seen_aliases: set[str] = set()
    today = _datetime.date.today()
    for index, model in enumerate(models):
        label = f"models[{index}]"
        if not isinstance(model, dict):
            errors.append(f"{label} must be an object")
            continue
        model_id = str(model.get("id", "")).strip()
        if not model_id:
            errors.append(f"{label}.id is required")
            continue
        if model_id.lower() in seen_ids:
            errors.append(f"duplicate model id: {model_id}")
        seen_ids.add(model_id.lower())
        aliases = model.get("aliases", [])
        if not isinstance(aliases, list):
            errors.append(f"{model_id}.aliases must be a list")
            aliases = []
        for alias in aliases:
            key = str(alias).strip().lower()
            if not key or any(character.isspace() for character in key):
                errors.append(f"{model_id} has an invalid alias: {alias!r}")
                continue
            if key in seen_ids or key in seen_aliases:
                errors.append(f"duplicate model alias: {alias}")
            seen_aliases.add(key)
        license_id = str(model.get("license", "")).strip()
        if license_id not in allowed and license_id not in custom:
            errors.append(f"{model_id}: license {license_id or '(missing)'} is not approved or custom-reviewed")
        url = str(model.get("license_url", ""))
        if not url.startswith("https://"):
            errors.append(f"{model_id}: license_url must be HTTPS")
        reviewed = str(model.get("reviewed", ""))
        try:
            reviewed_date = _datetime.date.fromisoformat(reviewed)
            if reviewed_date > today:
                errors.append(f"{model_id}: reviewed date is in the future")
        except ValueError:
            errors.append(f"{model_id}: reviewed must be an ISO date")
        uses = model.get("uses")
        if not isinstance(uses, dict):
            errors.append(f"{model_id}: uses must be an object")
        else:
            unknown = set(uses) - set(USES)
            if unknown:
                errors.append(f"{model_id}: unknown uses {sorted(unknown)}")
            if not any(uses.get(use) is True for use in USES):
                errors.append(f"{model_id}: at least one use must be approved")
            for use in USES:
                if use in uses and not isinstance(uses[use], bool):
                    errors.append(f"{model_id}: uses.{use} must be boolean")
        requirements = model.get("requirements", [])
        if not isinstance(requirements, list) or not all(
            isinstance(item, str) and item.strip() for item in requirements
        ):
            errors.append(f"{model_id}: requirements must be a list of strings")
        if license_id in custom and not requirements:
            errors.append(f"{model_id}: custom licenses require explicit obligations")
    return errors


def check_model_manifest(
    manifest: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify every model bundled with a release is approved for shipping."""
    entries = manifest.get("bundled_models", [])
    if not isinstance(entries, list):
        return {"approved": False, "reason": "bundled_models must be a list", "decisions": []}
    decisions = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            decisions.append(
                {
                    "approved": False,
                    "status": "invalid",
                    "model_id": f"bundled_models[{index}]",
                    "reason": "Entry must be an object",
                    "requirements": [],
                }
            )
            continue
        decisions.append(
            check_model(
                str(entry.get("id", "")),
                str(entry.get("license", "")),
                "shipping",
                policy,
            )
        )
    failures = [decision for decision in decisions if not decision["approved"]]
    return {
        "approved": not failures,
        "reason": "All bundled models are approved for shipping"
        if not failures
        else f"{len(failures)} bundled model(s) are not approved for shipping",
        "decisions": decisions,
    }
