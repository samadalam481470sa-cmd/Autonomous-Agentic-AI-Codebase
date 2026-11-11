"""Build a downloadable, runnable Aetherion OmniForge bundle.

The archive contains the prebuilt dashboard, the Python services, launchers for
Linux/macOS and Windows, docs and tests. It needs Python 3.11+ and nothing else;
Node, Docker, a database server and a cloud account are not required.

    python scripts/package_local.py --output-dir dist
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT_FILES = [
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "requirements.txt",
    "aetherion.py",
    "run.sh",
    "run.bat",
    "AETHERION.md",
]
ROOT_DIRS = [
    "apps",
    "services",
    "scripts",
    "docs",
    "tests",
    "database",
    "third_party",
    "packages",
    "deploy",
]
EXCLUDED_PARTS = {
    ".git", ".venv", "node_modules", "__pycache__", ".agent", "workspaces",
    ".freebuff", ".pytest_cache", ".mypy_cache", "build",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm",
                     ".log", ".zip", ".sha256"}
EXECUTABLE = {"run.sh", "aetherion.py"}
QUICKSTART = """Aetherion OmniForge - local bundle
==================================

1. Install Python 3.11 or newer.
2. Linux/macOS:  ./run.sh
   Windows:      run.bat
3. Open the dashboard URL printed in the terminal (normally
   http://127.0.0.1:8000/dashboard) and paste the token printed there too.

Optional local models:
  - Install Ollama from https://ollama.com, then run the pull command shown
    on the Device page.
  - Or run a llama.cpp OpenAI-compatible server and set
    LOCAL_MODEL_BASE_URL=http://127.0.0.1:9931/v1

Everything runs on this computer. There is no telemetry and no cloud account.
Docs: docs/LOCAL_RUNTIME.md
"""


class BundleError(RuntimeError):
    pass


def _project_version(root: Path) -> str:
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return "0.1.0"
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else "0.1.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for name in ROOT_FILES:
        path = root / name
        if not path.is_file():
            raise BundleError(f"Missing required file: {name}")
        files.append(path)
    for name in ROOT_DIRS:
        directory = root / name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if relative.parts[0] == "dist":
                continue
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            if path.name.startswith(".env"):
                continue
            files.append(path)
    return sorted(set(files))


def build_bundle(output_dir: Path | str | None = None,
                 root: Path | str | None = None,
                 version: str | None = None) -> dict:
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    dashboard = root / "apps" / "dashboard" / "dist" / "index.html"
    if not dashboard.is_file():
        raise BundleError(
            "Dashboard bundle missing. Run: cd apps/dashboard && npm ci && npm run build"
        )
    dashboard_html = dashboard.read_text(encoding="utf-8")
    if "/dashboard/assets/" not in dashboard_html:
        raise BundleError("Dashboard build does not reference /dashboard/assets/")
    editor_assets = root / "apps" / "web" / "assets"
    for name in ("monaco-entry.js", "monaco-entry.css", "ts.worker.js", "MONACO_LICENSE.txt"):
        if not (editor_assets / name).is_file():
            raise BundleError(
                "Browser editor assets missing. Run: cd apps/web && npm ci && npm run build"
            )

    version = version or _project_version(root)
    output = Path(output_dir or root / "dist").resolve()
    output.mkdir(parents=True, exist_ok=True)
    label = f"aetherion-omniforge-{version}"
    archive = output / f"{label}.zip"

    files = _iter_files(root)
    manifest_files: dict[str, str] = {}
    for path in files:
        manifest_files[path.relative_to(root).as_posix()] = _sha256(path)

    manifest = {
        "name": "Aetherion OmniForge",
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entrypoint": "aetherion.py",
        "launchers": ["run.sh", "run.bat"],
        "python_requires": ">=3.11",
        "platform": "any",
        "dashboard_built": True,
        "file_count": len(files),
        "files": manifest_files,
        "notes": [
            "Runs fully on the local CPU, GPU and RAM.",
            "No cloud account, Docker daemon or external database is required.",
            "No telemetry is sent by the application.",
        ],
    }

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as bundle:
        for path in files:
            relative = path.relative_to(root).as_posix()
            arcname = f"{label}/{relative}"
            bundle.write(path, arcname)
            if path.name in EXECUTABLE:
                info = bundle.getinfo(arcname)
                info.external_attr = (0o755 << 16)
        bundle.writestr(f"{label}/QUICKSTART.txt", QUICKSTART)
        bundle.writestr(f"{label}/MANIFEST.json",
                        json.dumps(manifest, indent=2, sort_keys=True))

    digest = _sha256(archive)
    checksum = output / f"{archive.name}.sha256"
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return {
        "archive": archive,
        "checksum": checksum,
        "sha256": digest,
        "prefix": label,
        "files": len(files),
        "bytes": archive.stat().st_size,
        "version": version,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the local Aetherion bundle")
    parser.add_argument("--output-dir", default=None,
                        help="Destination directory (default ./dist)")
    parser.add_argument("--version", default=None, help="Override the version")
    args = parser.parse_args(argv)
    try:
        result = build_bundle(output_dir=args.output_dir, version=args.version)
    except BundleError as error:
        print(f"Bundle failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "archive": str(result["archive"]),
        "checksum": str(result["checksum"]),
        "sha256": result["sha256"],
        "files": result["files"],
        "bytes": result["bytes"],
        "version": result["version"],
        "host": platform.platform(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
