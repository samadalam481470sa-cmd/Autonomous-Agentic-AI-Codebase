"""The downloadable local bundle: contents, checksum and safety exclusions."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import package_local

ROOT = Path(__file__).resolve().parents[1]


def test_bundle_is_runnable_and_clean(tmp_path):
    result = package_local.build_bundle(output_dir=tmp_path, root=ROOT)
    archive = result["archive"]
    assert archive.is_file()
    assert archive.stat().st_size > 10000
    prefix = result["prefix"]

    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        for relative in [
            "aetherion.py",
            "run.sh",
            "run.bat",
            "AETHERION.md",
            "apps/dashboard/dist/index.html",
            "apps/web/assets/monaco-entry.js",
            "apps/web/assets/monaco-entry.css",
            "services/api/device.py",
            "docs/LOCAL_RUNTIME.md",
            "MANIFEST.json",
            "QUICKSTART.txt",
        ]:
            assert f"{prefix}/{relative}" in names

        assert not any(
            "__pycache__" in name
            or "/.venv/" in name
            or name.endswith(".sqlite3")
            or "/node_modules/" in name
            for name in names
        )

        manifest = json.loads(bundle.read(f"{prefix}/MANIFEST.json"))
        assert manifest["entrypoint"] == "aetherion.py"
        assert manifest["dashboard_built"] is True
        assert manifest["file_count"] > 20
        assert (
            manifest["files"]["aetherion.py"]
            == hashlib.sha256((ROOT / "aetherion.py").read_bytes()).hexdigest()
        )

        mode = bundle.getinfo(f"{prefix}/run.sh").external_attr >> 16
        assert mode & 0o111

    checksum = result["checksum"].read_text(encoding="utf-8").split()[0]
    assert checksum == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_bundle_refuses_to_ship_without_dashboard(tmp_path):
    root = tmp_path / "root"
    (root / "apps/dashboard/dist").mkdir(parents=True)
    for name in [
        "README.md",
        "LICENSE",
        "pyproject.toml",
        "requirements.txt",
        "aetherion.py",
        "run.sh",
        "run.bat",
        "AETHERION.md",
    ]:
        (root / name).write_text("placeholder", encoding="utf-8")

    with pytest.raises(package_local.BundleError):
        package_local.build_bundle(output_dir=tmp_path / "out", root=root)
