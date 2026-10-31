#!/usr/bin/env python3
"""Reproducible Code-OSS workbench integration.

The original repository retains its existing Electron/Monaco fallback.
Code-OSS is cloned separately at a reviewed upstream SHA, then receives a
local-only extension overlay and product rebranding. Never copies Microsoft's
proprietary VS Code binaries or marketplace configuration.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED_TAG = "1.144.0"
PINNED_COMMIT = "2c33b50b16c472efe58357d1d2a8a5414bc23fbf"
UPSTREAM_URL = "https://github.com/microsoft/vscode.git"
EXTENSION = ROOT / "code_oss_integration" / "extension"
DEST_EXTENSION = "agentic-local"

GALLERY = {
    "serviceUrl": "https://open-vsx.org/vscode/gallery",
    "itemUrl": "https://open-vsx.org/vscode/item",
    "resourceUrlTemplate": "https://open-vsx.org/vscode/unpkg/{publisher}/{name}/{version}/{path}",
    "extensionUrlTemplate": "https://open-vsx.org/vscode/gallery/{publisher}/{name}/latest",
}

def invoke(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()

def ensure_upstream(source: Path, clone: bool) -> None:
    if clone:
        if source.exists():
            raise RuntimeError("Refusing to clone into an existing directory")
        source.parent.mkdir(parents=True, exist_ok=True)
        invoke("git", "clone", "--depth", "1", "--branch", PINNED_TAG,
               "--", UPSTREAM_URL, str(source))
    if not (source / ".git").exists() or not (source / "product.json").is_file():
        raise RuntimeError("Expected a Code-OSS git checkout with product.json")
    revision = invoke("git", "rev-parse", "HEAD", cwd=source)
    if revision != PINNED_COMMIT:
        raise RuntimeError(f"Unreviewed Code-OSS checkout {revision}; expected {PINNED_COMMIT}")

def branded_product(original: dict) -> dict:
    """Change only audited, owned product settings; retain OSS metadata."""
    result = dict(original)
    result.update({
        "nameShort": "Agentic Workbench",
        "nameLong": "Agentic Workbench",
        "applicationName": "agentic-workbench",
        "dataFolderName": ".agentic-workbench",
        "sharedDataFolderName": ".agentic-workbench-shared",
        "win32MutexName": "agenticworkbench",
        "win32DirName": "Agentic Workbench",
        "win32NameVersion": "Agentic Workbench",
        "win32RegValueName": "AgenticWorkbench",
        "win32ShellNameShort": "Agentic Workbench",
        "win32AppUserModelId": "Agentic.Workbench",
        "darwinBundleIdentifier": "dev.autonomous.agenticworkbench",
        "linuxDesktopName": "dev.autonomous.AgenticWorkbench",
        "linuxIconName": "agentic-workbench",
        "urlProtocol": "agentic-workbench",
        "reportIssueUrl": "https://github.com/samadalam481470sa-cmd/Autonomous-Agentic-AI-Codebase/issues/new",
        "serverApplicationName": "agentic-workbench-server",
        "serverDataFolderName": ".agentic-workbench-server",
        "tunnelApplicationName": "agentic-workbench-tunnel",
        "win32TunnelServiceMutex": "agenticworkbenchtunnel",
        "extensionsGallery": GALLERY.copy(),
        "linkProtectionTrustedDomains": sorted(set(
            original.get("linkProtectionTrustedDomains", []) + ["https://open-vsx.org"]
        )),
    })
    # Stable UUIDs avoid collision with the stock Code-OSS distribution.
    for field in (
        "win32x64AppId", "win32arm64AppId", "win32x64UserAppId",
        "win32arm64UserAppId", "darwinProfileUUID", "darwinProfilePayloadUUID",
    ):
        result[field] = "{" + str(uuid.uuid5(uuid.NAMESPACE_DNS, f"agentic-workbench:{field}")).upper() + "}"
    # These upstream fields refer to product-specific hosted services that
    # are not a capability of this independent local-first distribution.
    for field in ("defaultChatAgent", "voiceWsUrl", "agentsTelemetryAppName",
                  "builtInExtensionsEnabledWithAutoUpdates", "trustedExtensionAuthAccess"):
        result.pop(field, None)
    return result

def check_product(product: dict) -> None:
    if product.get("applicationName") != "agentic-workbench":
        raise RuntimeError("Missing Agentic Workbench branding")
    if product.get("extensionsGallery") != GALLERY:
        raise RuntimeError("Incorrect Open VSX configuration")
    if product.get("defaultChatAgent") is not None:
        raise RuntimeError("Vendor hosted chat identity remains configured")
    if product.get("licenseName") != "MIT":
        raise RuntimeError("OSS MIT licensing must remain present")

def copy_overlay(source: Path) -> None:
    target = source / "extensions" / DEST_EXTENSION
    if target.is_symlink():
        raise RuntimeError("Refusing a symlink extension destination")
    target.mkdir(parents=True, exist_ok=True)
    for item in EXTENSION.rglob("*"):
        if item.is_dir():
            continue
        relative = item.relative_to(EXTENSION)
        dst = target / relative
        if dst.is_symlink():
            raise RuntimeError(f"Refusing symlink overwrite: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dst)

def validate_overlay(source: Path) -> None:
    check_product(json.loads((source / "product.json").read_text(encoding="utf-8")))
    for item in EXTENSION.rglob("*"):
        if not item.is_file():
            continue
        imported = source / "extensions" / DEST_EXTENSION / item.relative_to(EXTENSION)
        if not imported.is_file() or imported.read_bytes() != item.read_bytes():
            raise RuntimeError(f"Missing or stale Code-OSS overlay: {imported}")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".local" / "code-oss")
    parser.add_argument("--clone", action="store_true", help="Clone the pinned upstream release")
    parser.add_argument("--verify", action="store_true", help="Only inspect an existing prepared tree")
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    if args.clone and args.verify:
        parser.error("--clone and --verify are mutually exclusive")
    ensure_upstream(source, args.clone)
    if args.verify:
        validate_overlay(source)
        print(f"Verified Code-OSS {PINNED_TAG} at {PINNED_COMMIT}")
        return
    product_file = source / "product.json"
    original = json.loads(product_file.read_text(encoding="utf-8"))
    product = branded_product(original)
    check_product(product)
    product_file.write_text(json.dumps(product, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")
    copy_overlay(source)
    validate_overlay(source)
    print(f"Prepared Agentic Workbench overlay on Code-OSS {PINNED_TAG} ({PINNED_COMMIT})")
    print("This does not build or sign a Code-OSS desktop installer.")

if __name__ == "__main__":
    main()
