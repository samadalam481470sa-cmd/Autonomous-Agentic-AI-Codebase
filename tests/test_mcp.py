"""The MCP client only talks to operator-configured local servers."""
import json
import sys
from pathlib import Path

import pytest

from services.api import mcp

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_echo_server.py"


def write_config(tmp_path, monkeypatch, servers):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": servers}), encoding="utf-8")
    monkeypatch.setenv("MCP_SERVERS_PATH", str(path))
    monkeypatch.setenv("MCP_ENABLED", "1")
    return path


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    assert mcp.enabled() is False


def test_invalid_server_definitions_are_dropped(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, [
        {"name": "Bad Name", "command": "python"},
        {"name": "ok", "command": "python", "args": ["-c"], "enabled": True},
        {"name": "shell", "command": "sh\nrm -rf /"},
        {"name": "toomany", "command": "python", "args": ["x"] * 40},
    ])
    assert [item["name"] for item in mcp.servers()] == ["ok"]


def test_stdio_roundtrip_lists_and_calls_a_tool(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, [{
        "name": "echo",
        "command": sys.executable,
        "args": [str(FIXTURE)],
        "enabled": True,
    }])
    with mcp.McpSession(mcp.spec("echo")) as session:
        tools = session.tools()
        assert [tool["name"] for tool in tools] == ["echo"]
        result = session.call_tool("echo", {"text": "hi"})
        assert result["is_error"] is False
        assert "echo:hi" in json.dumps(result["content"])


def test_unknown_server_is_reported(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, [])
    with pytest.raises(mcp.McpError):
        mcp.spec("missing")


def test_missing_binary_fails_cleanly(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, [{
        "name": "missing",
        "command": "definitely-not-installed-mcp-server",
        "args": [],
    }])
    with pytest.raises(mcp.McpError) as error:
        with mcp.McpSession(mcp.spec("missing"), timeout=2):
            pass
    assert "Could not start MCP server" in str(error.value)


def test_registering_a_server_requires_a_valid_definition(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, [])
    with pytest.raises(ValueError):
        mcp.register({"name": "BAD", "command": "python"})
    saved = mcp.register({"name": "docs", "command": "python", "args": ["-m", "server"]})
    assert saved["name"] == "docs"
    assert [item["name"] for item in mcp.servers()] == ["docs"]
    with pytest.raises(ValueError):
        mcp.register({"name": "docs", "command": "python"})
