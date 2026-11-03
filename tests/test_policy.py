"""The policy gate fails closed and enforces role, autonomy and path limits."""
import json

from services.api import policy


def test_unknown_role_tool_and_autonomy_are_denied():
    assert policy.decide(role="ghost", autonomy="ask", tool="read_file")["decision"] == "deny"
    assert policy.decide(role="planner", autonomy="ask", tool="rm_rf")["decision"] == "deny"
    assert policy.decide(role="planner", autonomy="god", tool="read_file")["decision"] == "deny"


def test_ask_mode_can_read_but_never_write_or_run():
    assert policy.decide(role="builder", autonomy="ask", tool="read_file")["decision"] == "allow"
    assert policy.decide(role="builder", autonomy="ask", tool="write_file",
                         target="src/a.py", allowed_paths=["src"])["decision"] == "deny"
    assert policy.decide(role="builder", autonomy="ask", tool="run_command",
                         allowed_paths=["src"])["decision"] == "deny"


def test_read_only_roles_cannot_write_even_in_sandbox():
    for role in ("planner", "reviewer", "security"):
        result = policy.decide(role=role, autonomy="sandbox", tool="write_file",
                               target="src/a.py", allowed_paths=["src"])
        assert result["decision"] == "deny"
        assert result["reason"] == "tool_not_allowed_for_role"


def test_worktree_writes_require_an_allowed_path():
    assert policy.decide(role="builder", autonomy="worktree", tool="write_file",
                         target="src/auth/a.py", allowed_paths=["src/auth"])["decision"] == "allow"
    denied = policy.decide(role="builder", autonomy="worktree", tool="write_file",
                           target="src/other.py", allowed_paths=["src/auth"])
    assert denied["decision"] == "deny"
    assert denied["reason"] == "target_outside_allowed_paths"


def test_path_escape_and_absolute_targets_are_rejected():
    for target in ("../outside.py", "/etc/passwd", "src/../../escape.py", ""):
        result = policy.decide(role="builder", autonomy="worktree", tool="write_file",
                               target=target, allowed_paths=["src"])
        assert result["decision"] == "deny", target


def test_commands_need_approval_in_worktree_and_are_allowed_in_sandbox_tests():
    worktree = policy.decide(role="builder", autonomy="worktree", tool="run_command",
                             allowed_paths=["src"])
    assert worktree["decision"] == "require_approval"
    sandbox_tests = policy.decide(role="tester", autonomy="sandbox", tool="run_tests")
    assert sandbox_tests["decision"] == "allow"


def test_dependencies_and_merges_always_need_a_human():
    dependency = policy.decide(role="builder", autonomy="sandbox",
                               tool="install_dependency", new_dependency=True,
                               approved=True)
    assert dependency["decision"] == "allow"
    merge = policy.decide(role="integrator", autonomy="sandbox", tool="git_merge")
    assert merge["decision"] == "require_approval"
    assert merge["reason"] == "merge_requires_human"
    assert policy.decide(role="integrator", autonomy="sandbox",
                         tool="git_merge", approved=True)["decision"] == "require_approval"


def test_network_requires_sandbox_and_an_allowlisted_host():
    denied = policy.decide(role="builder", autonomy="worktree", tool="network_fetch",
                           network_host="api.example.com", allowed_hosts=["api.example.com"])
    assert denied["decision"] == "deny"
    new_host = policy.decide(role="builder", autonomy="sandbox", tool="network_fetch",
                             network_host="evil.example", allowed_hosts=["api.example.com"])
    assert new_host["decision"] == "require_approval"
    allowed = policy.decide(role="builder", autonomy="sandbox", tool="network_fetch",
                            network_host="api.example.com", allowed_hosts=["api.example.com"])
    assert allowed["decision"] == "allow"


def test_audit_appends_private_jsonl(tmp_path):
    target = tmp_path / "audit.jsonl"
    policy.audit({"role": "builder", "autonomy": "sandbox", "tool": "run_command",
                  "target": "npm test", "decision": "require_approval",
                  "risk": "command", "reason": "command_requires_approval",
                  "token": "never-written"}, path=target)
    record = json.loads(target.read_text(encoding="utf-8").strip())
    assert record["tool"] == "run_command"
    assert "token" not in record
    assert target.stat().st_mode & 0o777 == 0o600
