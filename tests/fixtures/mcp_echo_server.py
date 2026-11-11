"""Minimal MCP stdio server used by the MCP client tests.

Speaks newline-delimited JSON-RPC 2.0: initialize, tools/list and tools/call.
"""
import json
import sys


def reply(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            continue
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            payload = reply(request_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo", "version": "0.0.1"},
            })
        elif method == "tools/list":
            payload = reply(request_id, {"tools": [{
                "name": "echo",
                "description": "Echo the provided text",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
            }]})
        elif method == "tools/call":
            arguments = (message.get("params") or {}).get("arguments") or {}
            payload = reply(request_id, {
                "content": [{"type": "text", "text": "echo:" + str(arguments.get("text", ""))}],
                "isError": False,
            })
        elif request_id is None:
            continue
        else:
            payload = {"jsonrpc": "2.0", "id": request_id,
                       "error": {"code": -32601, "message": "unknown method"}}
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
