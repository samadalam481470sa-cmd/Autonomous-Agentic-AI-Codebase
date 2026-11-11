"""Install the Node and Chromium pieces the browser suite needs.

Every step is idempotent: dependency installs are stamped with the lockfile
hash they came from, editor assets are rebuilt only when a source is newer than
the build, and Chromium is downloaded only when it is missing. Re-running on a
warm checkout therefore does no work and returns immediately.

    python scripts/bootstrap_dev.py              # provision everything
    python scripts/bootstrap_dev.py --check      # report gaps, change nothing
    python scripts/bootstrap_dev.py --with-deps  # also install the Linux libraries
    python scripts/bootstrap_dev.py --dashboard  # also install dashboard dependencies
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
WEB = Path("apps/web")
DASHBOARD = Path("apps/dashboard")
STAMP = ".bootstrap-lock"
# The editor bundle is generated: it is gitignored and must be rebuilt locally.
ASSETS = ("monaco-entry.js", "monaco-entry.css", "editor.worker.js",
          "ts.worker.js", "MONACO_LICENSE.txt")
SOURCES = ("build.mjs", "monaco-entry.js", "index.html", "studio.html",
           "control.html", "package.json")
CHROMIUM_PATTERNS = (
    "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
    "chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell",
    "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
    "chromium-*/chrome-linux*/chrome",
    "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    "chromium-*/chrome-win*/chrome.exe",
)


class Missing(RuntimeError):
    """A required tool is not installed."""


class Step(NamedTuple):
    label: str
    command: list[str]
    cwd: Path
    stamp: Path | None = None


def npm() -> str:
    found = shutil.which("npm")
    if not found:
        raise Missing("npm is not on PATH; install Node.js 20 or newer")
    return found


def npm_command(*args: str) -> list[str]:
    """npm is npm.cmd on Windows, so it needs the command interpreter there."""
    executable = npm()
    return ["cmd", "/c", executable, *args] if os.name == "nt" else [executable, *args]


def lock_hash(app: Path) -> str:
    lock = app / "package-lock.json"
    if not lock.is_file():
        return ""
    return hashlib.sha256(lock.read_bytes()).hexdigest()[:16]


def dependencies_current(root: Path, app: Path) -> bool:
    """True when node_modules was installed from the lockfile that is present."""
    app = root / app
    stamp = app / "node_modules" / STAMP
    return (stamp.is_file()
            and stamp.read_text(encoding="utf-8").strip() == lock_hash(app)
            and (app / "node_modules" / ".bin").is_dir())


def assets_current(root: Path) -> bool:
    """True when every generated editor asset is newer than its sources."""
    web = root / WEB
    built = [web / "assets" / name for name in ASSETS]
    if not all(path.is_file() for path in built):
        return False
    oldest_asset = min(path.stat().st_mtime for path in built)
    source_times = [(web / name).stat().st_mtime for name in SOURCES if (web / name).is_file()]
    return max(source_times or [0]) <= oldest_asset


def browsers_root() -> Path:
    custom = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    return Path(custom) if custom else Path.home() / ".cache" / "ms-playwright"


def chromium_binary() -> Path | None:
    for pattern in CHROMIUM_PATTERNS:
        matches = sorted(browsers_root().glob(pattern),
                         key=lambda path: path.stat().st_mtime)
        if matches:
            return matches[-1]
    return None


def missing_libraries(binary: Path) -> list[str]:
    """Shared objects Chromium cannot load; empty when it can start."""
    if not shutil.which("ldd"):
        return []
    try:
        result = subprocess.run(["ldd", str(binary)], capture_output=True,
                                text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    names = set()
    for line in result.stdout.splitlines():
        # ldd prints "\tlibnspr4.so => not found"; the soname is before the arrow.
        if "not found" in line:
            names.add(line.split("=>")[0].strip() or line.split("not found")[0].strip())
    return sorted(names)


def fontconfig_missing() -> bool:
    """Chromium aborts while shaping text when no fontconfig config exists."""
    if os.name == "nt" or sys.platform == "darwin":
        return False
    return not Path("/etc/fonts/fonts.conf").is_file()


def plan(root: Path = ROOT, *, with_deps: bool = False, dashboard: bool = False,
         force: bool = False) -> list[Step]:
    """The steps still needed, in order; empty when the checkout is ready."""
    steps: list[Step] = []
    apps = (WEB, DASHBOARD) if dashboard else (WEB,)
    for app in apps:
        if force or not dependencies_current(root, app):
            steps.append(Step(
                label="install " + str(app) + " dependencies",
                command=npm_command("ci"),
                cwd=root / app,
                stamp=root / app / "node_modules" / STAMP,
            ))
    if force or not assets_current(root):
        steps.append(Step("build browser editor assets",
                          npm_command("run", "build"), root / WEB))
    binary = chromium_binary()
    if force or binary is None:
        command = npm_command("exec", "--yes", "--", "playwright", "install")
        if with_deps:
            command.append("--with-deps")
        command.append("chromium")
        steps.append(Step("download Chromium", command, root / WEB))
    elif with_deps and missing_libraries(binary):
        steps.append(Step(
            "install Chromium system libraries",
            npm_command("exec", "--yes", "--", "playwright", "install-deps", "chromium"),
            root / WEB))
    return steps


def report_environment() -> None:
    """Warn about the two failures that otherwise look like broken tests."""
    binary = chromium_binary()
    if binary is None:
        print("warning: Chromium is not installed; run this script without --check",
              file=sys.stderr)
        return
    missing = missing_libraries(binary)
    if missing:
        print("warning: Chromium cannot load: " + ", ".join(missing), file=sys.stderr)
        print("         on Linux run this script with --with-deps (needs root)",
              file=sys.stderr)
    if fontconfig_missing():
        print("warning: no /etc/fonts/fonts.conf; headless Chromium aborts on any"
              " page that draws text", file=sys.stderr)
        print("         point FONTCONFIG_FILE at a fonts.conf listing an installed font",
              file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="report missing pieces and exit non-zero; change nothing")
    parser.add_argument("--force", action="store_true",
                        help="run every step even when it already looks current")
    parser.add_argument("--with-deps", action="store_true",
                        help="also install the Linux libraries Chromium needs (needs root)")
    parser.add_argument("--dashboard", action="store_true",
                        help="also install apps/dashboard dependencies")
    args = parser.parse_args(argv)
    try:
        steps = plan(with_deps=args.with_deps, dashboard=args.dashboard,
                     force=args.force)
    except (Missing, FileNotFoundError) as error:
        print("bootstrap: " + str(error), file=sys.stderr)
        return 2
    if args.check:
        for step in steps:
            print("missing: " + step.label)
        report_environment()
        return 1 if steps else 0
    started = time.monotonic()
    for step in steps:
        print("bootstrap: " + step.label, flush=True)
        result = subprocess.run(step.command, cwd=step.cwd, check=False)
        if result.returncode != 0:
            print("bootstrap: failed: " + step.label, file=sys.stderr)
            return result.returncode
        if step.stamp is not None:
            step.stamp.parent.mkdir(parents=True, exist_ok=True)
            step.stamp.write_text(lock_hash(step.cwd) + "\n", encoding="utf-8")
    if not steps:
        print("bootstrap: nothing to do, everything is current")
    print("bootstrap: ready in %.1fs" % (time.monotonic() - started))
    report_environment()
    print("next: cd apps/web && npm run test:e2e")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
