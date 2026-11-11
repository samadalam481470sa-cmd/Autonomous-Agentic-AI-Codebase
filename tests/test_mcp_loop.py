"""The agent loop reaches configured MCP tools only through policy and approval."""
import json
import sys
from pathlib import Path

import pytest

from services.api import executor, mcp, policy


def _configure(tmp_path, monkeypatch):
    script = Path(__file__).parent / "fixtures" / "mcp_echo_server.py"
    config = tmp_path / "servers.json"
    config.write_text(
        json.dumps({"servers": [{"name": "echo", "command": sys.executable,
                                 "args": [str(script)]}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MCP_SERVERS_PATH", str(config))
    return config


def test_mcp_call_is_a_command_risk_tool_for_writers():
    assert policy.TOOL_RISK["mcp_call"] == "command"
    assert "mcp_call" in policy.ROLE_TOOLS["builder"]
    assert "mcp_call" in policy.ROLE_TOOLS["tester"]
    assert "mcp_call" not in policy.ROLE_TOOLS.get("reviewer", set())


def test_mcp_call_runs_a_configured_server_tool(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("MCP_ENABLED", "1")
    root = tmp_path / "tree"
    root.mkdir()
    with mcp.McpSession(mcp.spec("echo")) as session:
        tools = session.tools()
    assert tools, "the fixture server advertises at least one tool"
    name = tools[0]["name"]
    result = executor._run_tool(
        root, "mcp_call", {"server": "echo", "tool": name, "arguments": {}},
    )
    payload = json.loads(result)
    assert payload["server"] == "echo"
    assert payload["tool"] == name
    assert not payload["is_error"]


def test_mcp_call_is_refused_when_disabled(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    root = tmp_path / "tree"
    root.mkdir()
    result = executor._run_tool(
        root, "mcp_call", {"server": "echo", "tool": "anything", "arguments": {}},
    )
    assert result.startswith("MCP is disabled")


def test_unknown_mcp_server_is_a_tool_error(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setenv("MCP_ENABLED", "1")
    root = tmp_path / "tree"
    root.mkdir()
    with pytest.raises(ValueError):
        executor._run_tool(
            root, "mcp_call", {"server": "missing", "tool": "x", "arguments": {}},
        )

