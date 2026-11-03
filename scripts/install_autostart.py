"""Install a per-user autostart entry for the always-on local worker.

The worker runs only while this computer is powered on. This script writes a
user-level unit (systemd/launchd) so the worker starts at sign-in; it never
elevates privileges, enables a system service or starts one for you. Windows
prints a ``schtasks`` command for the owner to run.

    python scripts/install_autostart.py --print
    python scripts/install_autostart.py --install

After installing on Linux run:

    systemctl --user daemon-reload
    systemctl --user enable --now agentic-worker

Stop it any time with ``systemctl --user stop agentic-worker`` or the
``/api/worker/stop`` control.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT_NAME = "agentic-worker"
LABEL = "dev.autonomous.agentic.worker"
UNIT_ENV = {
    "AGENT_WORKER_ENABLED": "1",
    "AGENT_AUTONOMY": "1",
    "AGENT_HOST_TOOLCHAIN": "1",
    "AGENT_WORKER_POLICY": "always",
    "LOCAL_MODEL_ONLY": "1",
}


def _clean(value, label):
    text = str(value)
    if not text or "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError(f"{label} must be a non-empty single-line path")
    return text


def validate(root=None, python=None):
    root_path = Path(root or ROOT).expanduser().resolve()
    if not (root_path / "services" / "api" / "worker.py").is_file():
        raise ValueError("Root must contain services/api/worker.py")
    python_path = Path(python or sys.executable).expanduser().resolve()
    if not python_path.is_file():
        raise ValueError("Python interpreter does not exist")
    return root_path, python_path


def _quote(value):
    return '"' + _clean(value, "value").replace("\\", "\\\\").replace('"', '\\"') + '"'


def systemd_unit(python=None, root=None, home=None):
    root_path, python_path = validate(root, python)
    log_dir = Path(home or Path.home()) / ".local" / "state" / "agentic-ai"
    environment = "\n".join(f"Environment={key}={value}" for key, value in UNIT_ENV.items())
    return f"""[Unit]
Description=Autonomous Agentic AI local worker (runs while this computer is on)
After=network-online.target

[Service]
Type=simple
WorkingDirectory={_quote(str(root_path))}
ExecStart={_quote(str(python_path))} -m services.api.worker
{environment}
EnvironmentFile=-%h/.config/agentic-ai/worker.env
Restart=always
RestartSec=5
Nice=10
StandardOutput=append:{log_dir / 'worker.log'}
StandardError=append:{log_dir / 'worker.log'}

[Install]
WantedBy=default.target
"""


def launchd_plist(python=None, root=None, home=None):
    root_path, python_path = validate(root, python)
    home_path = Path(home or Path.home())
    payload = {
        "Label": LABEL,
        "ProgramArguments": [str(python_path), "-m", "services.api.worker"],
        "WorkingDirectory": str(root_path),
        "EnvironmentVariables": dict(UNIT_ENV),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(home_path / "Library" / "Logs" / "agentic-worker.log"),
        "StandardErrorPath": str(home_path / "Library" / "Logs" / "agentic-worker.log"),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True).decode("utf-8")


def windows_command(python=None, root=None):
    root_path, python_path = validate(root, python)
    inner = f'cmd /c cd /d "{root_path}" && "{python_path}" -m services.api.worker'
    return (
        'schtasks /Create /F /SC ONLOGON /RL LIMITED /TN "AgenticWorker" '
        f'/TR "{inner}"'
    )


def target(platform=None, home=None):
    platform = platform or sys.platform
    home_path = Path(home or Path.home())
    if platform.startswith("linux"):
        return home_path / ".config" / "systemd" / "user" / (UNIT_NAME + ".service")
    if platform == "darwin":
        return home_path / "Library" / "LaunchAgents" / (LABEL + ".plist")
    return None


def render(platform=None, python=None, root=None, home=None):
    platform = platform or sys.platform
    if platform.startswith("linux"):
        return {"platform": platform, "kind": "systemd",
                "path": target(platform, home), "content": systemd_unit(python, root, home)}
    if platform == "darwin":
        return {"platform": platform, "kind": "launchd",
                "path": target(platform, home), "content": launchd_plist(python, root, home)}
    return {"platform": platform, "kind": "schtasks", "path": None,
            "content": windows_command(python, root)}


def install(platform=None, python=None, root=None, home=None):
    rendered = render(platform, python, root, home)
    if rendered["path"] is None:
        rendered["installed"] = False
        rendered["instructions"] = rendered["content"]
        return rendered
    path = Path(rendered["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered["content"], encoding="utf-8")
    os.chmod(path, 0o600)
    rendered["installed"] = True
    if rendered["kind"] == "systemd":
        rendered["instructions"] = (
            f"systemctl --user daemon-reload && systemctl --user enable --now {UNIT_NAME}")
    else:
        rendered["instructions"] = f"launchctl load -w {path}"
    return rendered


def main(argv=None):
    parser = argparse.ArgumentParser(description="Autostart the local worker at sign-in")
    parser.add_argument("--install", action="store_true", help="Write the user-level unit")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="Print the unit instead of writing it (default)")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    try:
        if args.install:
            rendered = install(python=args.python, root=args.root)
        else:
            rendered = render(python=args.python, root=args.root)
    except (ValueError, OSError) as exc:
        print(f"Autostart error: {exc}", file=sys.stderr)
        return 1
    print(rendered["content"])
    if rendered.get("instructions"):
        print("\nNext step:", rendered["instructions"], file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
