#!/usr/bin/env python3
"""Aetherion OmniForge local launcher.

Starts the API and dashboard on this computer only, with a generated
administrator token, thermal monitoring and an optional keep-awake hold.

    python aetherion.py                 # open the printed dashboard URL
    python aetherion.py --no-open
    python aetherion.py --check         # probe hardware and exit

Nothing is installed, downloaded or sent off the machine by this script.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
DEFAULT_PORT = 8000
PORT_SCAN_ATTEMPTS = 20


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Aetherion OmniForge on this computer."
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address; loopback only (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to listen on (default 8000; next free port when busy)")
    parser.add_argument("--token", help="Administrator token; generated when omitted")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open the browser")
    parser.add_argument("--no-keep-awake", action="store_true",
                        help="Do not hold the machine awake")
    parser.add_argument("--hours", type=float, default=8.0,
                        help="Keep-awake budget in hours (default 8)")
    parser.add_argument("--check", action="store_true",
                        help="Print a hardware and backend report, then exit")
    return parser.parse_args(argv)


def _busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        return probe.connect_ex((host, port)) == 0


def _next_free_port(
    host: str, start: int, attempts: int = PORT_SCAN_ATTEMPTS
) -> int | None:
    for port in range(start, min(start + attempts, 65536)):
        if not _busy(host, port):
            return port
    return None


def _open_when_ready(url: str, timeout: float = 30.0) -> None:
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url + "/dashboard")
                    return
        except Exception:
            time.sleep(0.5)


def _print_banner(url: str, token: str, report: dict) -> None:
    thermal = report.get("thermal", {})
    recommendation = report.get("recommendation", {})
    memory = report.get("memory", {})
    print("")
    print("  Aetherion OmniForge · local runtime")
    print("  " + "-" * 46)
    print(f"  Dashboard   {url}/dashboard")
    print(f"  Token       {token}")
    print(f"  Device      {report.get('cpu', {}).get('model', 'unknown CPU')}")
    print(f"  Memory      {memory.get('total_mb') or '?'} MB")
    print(f"  Thermal     {thermal.get('state', 'unknown')}"
          f" ({thermal.get('max_c') if thermal.get('max_c') is not None else 'no sensor'}°C)")
    print(f"  Model       {recommendation.get('name', 'not detected')}"
          f" · {recommendation.get('runtime', 'ollama')}")
    print("  " + "-" * 46)
    print("  Paste the token into the dashboard. Press Ctrl+C to stop.")
    print("")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.host not in LOOPBACK:
        print("Refusing to bind a non-loopback address. Use 127.0.0.1.", file=sys.stderr)
        return 2
    requested_port = DEFAULT_PORT if args.port is None else args.port
    if not (1024 <= requested_port <= 65535):
        print("Port must be between 1024 and 65535.", file=sys.stderr)
        return 2
    if args.hours < 0.25 or args.hours > 48:
        print("--hours must be between 0.25 and 48.", file=sys.stderr)
        return 2

    os.chdir(ROOT)
    os.environ.setdefault("LOCAL_MODEL_ONLY", "1")
    os.environ.setdefault("DEVICE_THERMAL_GUARD", "1")
    os.environ.setdefault("AETHERION_CONTINUOUS", "1")
    os.environ.setdefault("AETHERION_LEARN_CAPTURE", "1")
    token = args.token or os.getenv("AGENT_ADMIN_TOKEN") or secrets.token_urlsafe(24)
    os.environ["AGENT_ADMIN_TOKEN"] = token

    from services.api import device  # imported after environment defaults

    if args.check:
        report = device.status_report()
        print(json.dumps({
            "dashboard_built": (ROOT / "apps/dashboard/dist/index.html").is_file(),
            "platform": report["platform"],
            "cpu": report["cpu"],
            "memory": report["memory"],
            "gpus": report["gpus"],
            "battery": report["battery"],
            "thermal": report["thermal"],
            "recommendation": report["recommendation"],
            "backends": report["backends"],
        }, indent=2))
        return 0

    port = requested_port
    if _busy(args.host, port):
        if args.port is not None:
            print(f"Port {port} on {args.host} is already in use.",
                  file=sys.stderr)
            print("If Aetherion is already running, use the token printed by "
                  "that terminal.", file=sys.stderr)
            print("Stop that process, or choose another port with --port 8123.",
                  file=sys.stderr)
            return 3
        replacement = _next_free_port(args.host, port + 1)
        if replacement is None:
            last = min(port + PORT_SCAN_ATTEMPTS, 65535)
            print(f"Ports {port}-{last} are all in use. Stop one or pass --port.",
                  file=sys.stderr)
            return 3
        print(f"Port {port} is already in use; using {replacement} instead. "
              "The token below belongs to this new process.", file=sys.stderr)
        port = replacement
    url = f"http://{args.host}:{port}"

    report = device.status_report()
    if not args.no_keep_awake:
        device.KEEP_AWAKE.start("launcher", ttl_seconds=int(args.hours * 3600))
    device.ensure_monitor()
    _print_banner(url, token, report)
    if not args.no_open:
        threading.Thread(
            target=_open_when_ready, args=(url,), name="open-browser", daemon=True
        ).start()

    import uvicorn

    config = uvicorn.Config(
        "services.api.main:app",
        host=args.host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        device.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
