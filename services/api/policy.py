"""Single policy gate for every agent tool action.

The gate combines the agent role, the autonomy level and the target. It fails
closed: unknown roles, tools and malformed paths are denied. Worktree writes
must match an allowed path prefix; new network hosts, dependencies and merges
require explicit human approval. This module performs no I/O except optional
audit append, so it is deterministic and directly testable.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

AUTONOMY = {"ask": 0, "worktree": 1, "sandbox": 2}
RISKS = ("read", "write", "command", "network", "dependency", "merge", "destructive")

ROLE_TOOLS = {
    "planner": {"read_file", "list_files", "search_files"},
    "explorer": {"read_file", "list_files", "search_files", "git_status"},
    "builder": {"read_file", "list_files", "search_files", "write_file", "apply_patch",
                "run_command", "run_tests", "git_status", "install_dependency", "network_fetch"},
    "tester": {"read_file", "list_files", "search_files", "write_file", "apply_patch",
               "run_command", "run_tests", "install_dependency", "network_fetch"},
    "reviewer": {"read_file", "list_files", "search_files", "git_diff"},
    "security": {"read_file", "list_files", "search_files", "scan_secrets",
                 "scan_dependencies"},
    "integrator": {"read_file", "search_files", "git_status", "git_merge"},
}

TOOL_RISK = {
    "read_file": "read", "list_files": "read", "search_files": "read",
    "git_status": "read", "git_diff": "read", "scan_secrets": "read",
    "scan_dependencies": "read",
    "write_file": "write", "apply_patch": "write",
    "run_command": "command", "run_tests": "command",
    "install_dependency": "dependency", "network_fetch": "network",
    "git_merge": "merge", "delete_path": "destructive",
}

READ_ONLY_ROLES = {"planner", "explorer", "reviewer", "security"}


def _target(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 400:
        return ""
    text = value.replace("\\", "/")
    path = Path(text)
    if path.is_absolute() or ".." in path.parts or "\x00" in text:
        return ""
    return path.as_posix()


def _within(target, allowed_paths) -> bool:
    if not target or target == "":
        return False
    if target == ".":
        return True
    for raw in allowed_paths:
        if not isinstance(raw, str) or not raw:
            continue
        allowed = raw.replace("\\", "/").rstrip("/")
        # "." means the project root, so every relative descendant is allowed.
        if allowed == "." or target == allowed or target.startswith(allowed + "/"):
            return True
    return False


def decide(*, role, autonomy, tool, target=None, allowed_paths=(),
           approved=False, network_host=None, allowed_hosts=(),
           new_dependency=False):
    """Return an allow/deny/require_approval decision with a stable reason."""
    if role not in ROLE_TOOLS:
        return _result("deny", None, "unknown_role")
    if autonomy not in AUTONOMY:
        return _result("deny", None, "unknown_autonomy")
    if tool not in TOOL_RISK:
        return _result("deny", None, "unknown_tool")
    risk = TOOL_RISK[tool]
    if tool not in ROLE_TOOLS[role]:
        return _result("deny", risk, "tool_not_allowed_for_role")
    if role in READ_ONLY_ROLES and risk != "read":
        return _result("deny", risk, "read_only_role")
    level = AUTONOMY[autonomy]

    if risk == "read":
        return _result("allow", risk, "read_allowed")

    if autonomy == "ask":
        return _result("deny", risk, "ask_mode_cannot_change_state")

    if risk in ("write", "destructive"):
        normalized = _target(target)
        if normalized is None or normalized == "":
            return _result("deny", risk, "invalid_target")
        if not _within(normalized, allowed_paths):
            return _result("deny", risk, "target_outside_allowed_paths")
        if risk == "destructive" and not approved:
            return _result("require_approval", risk, "destructive_action")
        return _result("allow", risk, "path_allowed")

    if risk == "command":
        if not (tool == "run_tests" and autonomy == "sandbox"):
            if not approved:
                return _result("require_approval", risk, "command_requires_approval")
        return _result("allow", risk, "command_approved")

    if risk == "dependency":
        if new_dependency and not approved:
            return _result("require_approval", risk, "new_dependency")
        if level < AUTONOMY["sandbox"] and not approved:
            return _result("require_approval", risk, "dependency_requires_sandbox_or_approval")
        return _result("allow", risk, "dependency_approved")

    if risk == "network":
        host = str(network_host or "").strip().lower()
        if not host or not isinstance(allowed_hosts, (list, tuple, set)):
            return _result("deny", risk, "network_host_required")
        known = {str(item).strip().lower() for item in allowed_hosts if item}
        if host not in known:
            if level < AUTONOMY["sandbox"] or not approved:
                return _result("require_approval", risk, "new_network_host")
            return _result("allow", risk, "new_host_approved")
        if level < AUTONOMY["sandbox"]:
            return _result("deny", risk, "network_requires_sandbox")
        return _result("allow", risk, "host_allowed")

    if risk == "merge":
        if autonomy == "sandbox":
            return _result("require_approval", risk, "merge_requires_human")
        return _result("require_approval", risk, "merge_requires_human")
    return _result("deny", risk, "unhandled_risk")


def _result(decision, risk, reason):
    return {"decision": decision, "risk": risk, "reason": reason}


def audit_path() -> Path:
    path = Path(os.getenv("POLICY_AUDIT_PATH", "./database/policy_audit.jsonl")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def audit(record: dict, *, path=None) -> dict:
    """Append one non-secret policy decision to the audit log."""
    safe = {
        "at": int(time.time()),
        "role": str(record.get("role", ""))[:64],
        "autonomy": str(record.get("autonomy", ""))[:32],
        "tool": str(record.get("tool", ""))[:64],
        "target": str(record.get("target", ""))[:300],
        "decision": str(record.get("decision", ""))[:32],
        "risk": str(record.get("risk", ""))[:32],
        "reason": str(record.get("reason", ""))[:200],
    }
    destination = Path(path) if path else audit_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, sort_keys=True) + "\n")
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return safe
