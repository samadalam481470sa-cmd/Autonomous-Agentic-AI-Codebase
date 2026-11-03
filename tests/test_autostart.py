"""Sign-in autostart generation for the always-on worker."""
import sys
from pathlib import Path

import pytest

from scripts import install_autostart as autostart

ROOT = Path(__file__).resolve().parents[1]


def test_systemd_unit_restarts_and_sets_local_flags(tmp_path):
    text = autostart.systemd_unit(sys.executable, ROOT, home=tmp_path)
    assert "ExecStart=" in text
    assert "-m services.api.worker" in text
    assert "Restart=always" in text
    assert "WantedBy=default.target" in text
    assert "AGENT_WORKER_ENABLED=1" in text
    assert "AGENT_HOST_TOOLCHAIN=1" in text
    assert "EnvironmentFile=-%h/.config/agentic-ai/worker.env" in text
    assert f"WorkingDirectory=" in text


def test_launchd_plist_is_valid_xml(tmp_path):
    text = autostart.launchd_plist(sys.executable, ROOT, home=tmp_path)
    assert "<key>RunAtLoad</key>" in text
    assert "<key>KeepAlive</key>" in text
    assert "services.api.worker" in text
    assert "AGENT_WORKER_ENABLED" in text


def test_windows_uses_an_onlogon_task():
    command = autostart.windows_command(sys.executable, ROOT)
    assert command.startswith("schtasks /Create")
    assert "/SC ONLOGON" in command
    assert "services.api.worker" in command


def test_install_writes_private_user_units(tmp_path):
    linux = autostart.install(platform="linux", python=sys.executable,
                              root=ROOT, home=tmp_path)
    assert linux["installed"] is True
    unit = Path(linux["path"])
    assert unit.is_file()
    assert unit.stat().st_mode & 0o777 == 0o600
    assert "systemctl --user" in linux["instructions"]

    mac = autostart.install(platform="darwin", python=sys.executable,
                            root=ROOT, home=tmp_path)
    assert Path(mac["path"]).is_file()

    windows = autostart.install(platform="win32", python=sys.executable,
                                root=ROOT, home=tmp_path)
    assert windows["installed"] is False
    assert windows["content"].startswith("schtasks")


def test_validation_rejects_an_unrelated_root(tmp_path):
    with pytest.raises(ValueError, match="services/api/worker.py"):
        autostart.validate(tmp_path)
    with pytest.raises(ValueError):
        autostart.systemd_unit(sys.executable, tmp_path)
    with pytest.raises(ValueError):
        autostart.systemd_unit("/bad\npath", ROOT)
