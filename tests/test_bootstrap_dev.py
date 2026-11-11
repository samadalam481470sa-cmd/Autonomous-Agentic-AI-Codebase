"""The browser bootstrap skips work that is already done."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "bootstrap_dev", Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_dev.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def app_with_modules(root, app_rel, lock="lock-one"):
    app = root / app_rel
    (app / "node_modules" / ".bin").mkdir(parents=True)
    (app / "package-lock.json").write_text(lock, encoding="utf-8")
    return app


def stamp(app):
    (app / "node_modules" / bootstrap.STAMP).write_text(
        bootstrap.lock_hash(app), encoding="utf-8")


def web_tree(root, *, source_age, asset_age):
    web = root / bootstrap.WEB
    (web / "assets").mkdir(parents=True)
    for name in bootstrap.SOURCES:
        (web / name).write_text("", encoding="utf-8")
        os.utime(web / name, (source_age, source_age))
    for name in bootstrap.ASSETS:
        (web / "assets" / name).write_text("", encoding="utf-8")
        os.utime(web / "assets" / name, (asset_age, asset_age))


def test_dependencies_are_current_only_for_the_installing_lockfile(tmp_path):
    app = app_with_modules(tmp_path, bootstrap.WEB)
    assert not bootstrap.dependencies_current(tmp_path, bootstrap.WEB)
    stamp(app)
    assert bootstrap.dependencies_current(tmp_path, bootstrap.WEB)
    (app / "package-lock.json").write_text("lock-two", encoding="utf-8")
    assert not bootstrap.dependencies_current(tmp_path, bootstrap.WEB)


def test_a_missing_bin_directory_is_never_current(tmp_path):
    app = app_with_modules(tmp_path, bootstrap.WEB)
    stamp(app)
    (app / "node_modules" / ".bin").rmdir()
    assert not bootstrap.dependencies_current(tmp_path, bootstrap.WEB)


def test_assets_are_rebuilt_only_when_a_source_is_newer(tmp_path):
    web_tree(tmp_path, source_age=1_000, asset_age=2_000)
    assert bootstrap.assets_current(tmp_path)
    os.utime(tmp_path / bootstrap.WEB / "monaco-entry.js", (3_000, 3_000))
    assert not bootstrap.assets_current(tmp_path)


def test_a_missing_asset_forces_a_rebuild(tmp_path):
    web_tree(tmp_path, source_age=1_000, asset_age=2_000)
    (tmp_path / bootstrap.WEB / "assets" / "ts.worker.js").unlink()
    assert not bootstrap.assets_current(tmp_path)


def test_plan_is_empty_for_a_ready_checkout(tmp_path, monkeypatch):
    stamp(app_with_modules(tmp_path, bootstrap.WEB))
    web_tree(tmp_path, source_age=1_000, asset_age=2_000)
    monkeypatch.setattr(bootstrap, "chromium_binary", lambda: Path("/browser"))
    assert bootstrap.plan(tmp_path) == []


def test_plan_lists_every_missing_piece(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "chromium_binary", lambda: None)
    labels = [step.label for step in bootstrap.plan(tmp_path)]
    assert any("dependencies" in label for label in labels)
    assert any("editor assets" in label for label in labels)
    assert any("Chromium" in label for label in labels)


def test_with_deps_reaches_the_playwright_command(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "chromium_binary", lambda: None)
    step = [item for item in bootstrap.plan(tmp_path, with_deps=True)
            if "Chromium" in item.label][0]
    assert "--with-deps" in step.command
    assert step.command[-1] == "chromium"


def test_with_deps_repairs_libraries_even_when_the_browser_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "chromium_binary", lambda: Path("/browser"))
    monkeypatch.setattr(bootstrap, "missing_libraries", lambda binary: ["libnspr4.so"])
    step = [item for item in bootstrap.plan(tmp_path, with_deps=True)
            if "libraries" in item.label][0]
    assert "install-deps" in step.command
    assert step.command[-1] == "chromium"


def test_dashboard_dependencies_are_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "chromium_binary", lambda: Path("/browser"))
    assert not any(str(bootstrap.DASHBOARD) in step.label
                   for step in bootstrap.plan(tmp_path))
    assert any(str(bootstrap.DASHBOARD) in step.label
               for step in bootstrap.plan(tmp_path, dashboard=True))


def test_check_mode_reports_without_running_anything(tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("--check must not run commands")

    monkeypatch.setattr(bootstrap.subprocess, "run", explode)
    monkeypatch.setattr(bootstrap, "report_environment", lambda: None)
    monkeypatch.setattr(bootstrap, "chromium_binary", lambda: None)
    pending = bootstrap.plan(tmp_path)
    monkeypatch.setattr(bootstrap, "plan", lambda **kwargs: pending)
    assert bootstrap.main(["--check"]) == 1
    monkeypatch.setattr(bootstrap, "plan", lambda **kwargs: [])
    assert bootstrap.main(["--check"]) == 0


def test_missing_libraries_reports_sonames(tmp_path, monkeypatch):
    binary = tmp_path / "chrome"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/ldd")
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout="\tlibnspr4.so => not found\n\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6\n"))
    assert bootstrap.missing_libraries(binary) == ["libnspr4.so"]
