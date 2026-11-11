"""Minimal Model Context Protocol client over the stdio transport.

Servers are operator-configured in a JSON file; a request body can add one only
with an explicit approval header and only when ``MCP_ENABLED=1``. No shell is
used, argv is bounded, and each call is capped by a timeout. This is a client
for locally installed MCP servers, not a marketplace or a remote transport.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .studio import authorize

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "aetherion-local", "version": "0.1.0"}
DEFAULT_TIMEOUT = 12.0
MAX_ARGS = 32
MAX_ARG_CHARS = 500
MAX_MESSAGE_CHARS = 2_000_000
MAX_TOOLS = 200
NAME = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


class McpError(Exception):
    """Raised for transport, protocol and server failures."""


def enabled() -> bool:
    return os.getenv("MCP_ENABLED") == "1"


def config_path() -> Path:
    return Path(os.getenv("MCP_SERVERS_PATH", "./database/mcp_servers.json")).expanduser().resolve()


def _timeout() -> float:
    try:
        value = float(os.getenv("MCP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT)))
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT
    return max(1.0, min(value, 60.0))


def _clean_spec(raw: dict):
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    command = str(raw.get("command") or "").strip()
    if not NAME.fullmatch(name) or not command or len(command) > 300:
        return None
    if any(character in command for character in "\n\r\x00"):
        return None
    args = raw.get("args") or []
    if not isinstance(args, list) or len(args) > MAX_ARGS:
        return None
    cleaned = []
    for item in args:
        if not isinstance(item, str) or len(item) > MAX_ARG_CHARS:
            return None
        if "\x00" in item or "\n" in item:
            return None
        cleaned.append(item)
    cwd = raw.get("cwd")
    if cwd is not None:
        try:
            resolved = Path(str(cwd)).expanduser().resolve()
        except (OSError, RuntimeError):
            return None
        if not resolved.is_dir():
            return None
        cwd = str(resolved)
    return {"name": name, "command": command, "args": cleaned, "cwd": cwd,
            "enabled": bool(raw.get("enabled", True))}


def _load() -> list[dict]:
    path = config_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    servers = data.get("servers") if isinstance(data, dict) else data
    if not isinstance(servers, list):
        return []
    cleaned = []
    for item in servers[:50]:
        spec = _clean_spec(item)
        if spec is not None:
            cleaned.append(spec)
    return cleaned


def servers() -> list[dict]:
    return _load()


def spec(name: str) -> dict:
    for server in _load():
        if server["name"] == name:
            return server
    raise McpError("Unknown MCP server: " + str(name))


def register(entry: dict) -> dict:
    """Append an operator-approved server definition to the local config file."""
    spec_value = _clean_spec(entry)
    if spec_value is None:
        raise ValueError("Invalid MCP server definition")
    existing = _load()
    if any(server["name"] == spec_value["name"] for server in existing):
        raise ValueError("An MCP server with that name already exists")
    existing.append(spec_value)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"servers": existing}, indent=2) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return spec_value


class McpSession:
    """One short-lived stdio session: initialize, one operation, close."""

    def __init__(self, server: dict, timeout: float | None = None):
        self.server = server
        self.timeout = float(timeout or _timeout())
        self._queue: queue.Queue = queue.Queue()
        self._stderr: list[str] = []
        self._next_id = 0
        self.process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def start(self):
        argv = [self.server["command"], *self.server["args"]]
        kwargs = {
            "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8",
            "errors": "replace", "bufsize": 1, "shell": False,
        }
        if self.server.get("cwd"):
            kwargs["cwd"] = self.server["cwd"]
        try:
            self.process = subprocess.Popen(argv, **kwargs)
        except (OSError, ValueError) as error:
            raise McpError("Could not start MCP server: " + str(error))
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_reader.start()
        self.initialize()

    def _pump_stdout(self):
        stream = self.process.stdout if self.process else None
        if stream is None:
            self._queue.put(None)
            return
        try:
            for line in stream:
                text = line.strip()
                if not text or len(text) > MAX_MESSAGE_CHARS:
                    continue
                try:
                    self._queue.put(json.loads(text))
                except json.JSONDecodeError:
                    continue
        finally:
            self._queue.put(None)

    def _pump_stderr(self):
        stream = self.process.stderr if self.process else None
        if stream is None:
            return
        try:
            for line in stream:
                self._stderr.append(line.strip()[:500])
                del self._stderr[:-20]
        except (OSError, ValueError):
            return

    def _send(self, message: dict):
        if not self.process or not self.process.stdin:
            raise McpError("MCP server is not running")
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError) as error:
            raise McpError("Could not write to MCP server: " + str(error))

    def _await(self, request_id: int, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError("MCP server did not reply in time")
            try:
                message = self._queue.get(timeout=remaining)
            except queue.Empty:
                raise McpError("MCP server did not reply in time")
            if message is None:
                detail = self._stderr[-1] if self._stderr else "no diagnostics"
                raise McpError("MCP server closed the connection (" + detail + ")")
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
            # Notifications and unrelated replies are ignored for this call.

    def request(self, method: str, params: dict | None = None, timeout=None) -> dict:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method,
                    "params": params or {}})
        message = self._await(request_id, float(timeout or self.timeout))
        error = message.get("error")
        if error:
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise McpError("MCP error: " + str(detail)[:300])
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def notify(self, method: str, params: dict | None = None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self):
        self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self.notify("notifications/initialized")

    def tools(self) -> list[dict]:
        result = self.request("tools/list", {})
        raw = result.get("tools")
        if not isinstance(raw, list):
            return []
        tools = []
        for item in raw[:MAX_TOOLS]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            tools.append({
                "name": item["name"][:120],
                "description": str(item.get("description") or "")[:500],
                "input_schema": item.get("inputSchema") if isinstance(
                    item.get("inputSchema"), dict) else {},
            })
        return tools

    def call_tool(self, name: str, arguments: dict) -> dict:
        if not isinstance(name, str) or not name:
            raise McpError("Tool name is required")
        if not isinstance(arguments, dict):
            raise McpError("Tool arguments must be an object")
        if len(json.dumps(arguments)) > 200_000:
            raise McpError("Tool arguments are too large")
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        return {"content": result.get("content") or [], "is_error": bool(result.get("isError"))}

    def close(self):
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass


class ServerRequest(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    command: str = Field(min_length=1, max_length=300)
    args: list[str] = Field(default_factory=list, max_length=MAX_ARGS)
    cwd: str | None = Field(default=None, max_length=500)
    enabled: bool = True


class CallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


@router.get("/servers")
def list_servers(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return {
        "enabled": enabled(),
        "servers": [{"name": server["name"], "command": server["command"],
                     "args": server["args"], "cwd": server["cwd"],
                     "enabled": server["enabled"]} for server in servers()],
        "note": "Set MCP_ENABLED=1 to call operator-configured local MCP servers.",
    }


@router.post("/servers")
def add_server(body: ServerRequest,
               authorization: str | None = Header(default=None),
               x_confirm_change: str | None = Header(default=None)):
    authorize(authorization)
    if x_confirm_change != "approve":
        raise HTTPException(428, "Explicit human approval required")
    if not enabled():
        raise HTTPException(503, "Set MCP_ENABLED=1 to register MCP servers")
    try:
        return {"server": register(body.model_dump())}
    except ValueError as error:
        raise HTTPException(400, str(error))


@router.get("/{name}/tools")
def list_tools(name: str, authorization: str | None = Header(default=None)):
    authorize(authorization)
    if not enabled():
        raise HTTPException(503, "Set MCP_ENABLED=1 to query MCP servers")
    try:
        with McpSession(spec(name)) as session:
            return {"server": name, "tools": session.tools()}
    except McpError as error:
        raise HTTPException(502, str(error))


@router.post("/{name}/call")
def call_tool(name: str, body: CallRequest,
              authorization: str | None = Header(default=None),
              x_confirm_change: str | None = Header(default=None)):
    authorize(authorization)
    if x_confirm_change != "approve":
        raise HTTPException(428, "Explicit human approval required")
    if not enabled():
        raise HTTPException(503, "Set MCP_ENABLED=1 to call MCP servers")
    try:
        with McpSession(spec(name)) as session:
            return {"server": name, "tool": body.tool,
                    **session.call_tool(body.tool, body.arguments)}
    except McpError as error:
        raise HTTPException(502, str(error))
