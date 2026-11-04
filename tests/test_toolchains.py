"""Toolchain discovery, planning and argv-only execution."""
import shutil
from pathlib import Path

import pytest

from services.api import toolchains


def test_registry_is_broad_and_complete():
    assert len(toolchains.SPECS) >= 55
    for name, spec in toolchains.SPECS.items():
        assert spec["category"], name
        assert isinstance(spec["probes"], list), name
        assert spec["install"], name
    for name in ("python", "rust", "go", "c", "cpp", "csharp", "sql", "html", "zig"):
        assert name in toolchains.SPECS


def test_aliases_and_unknown_language():
    assert toolchains.normalize("JS") == "javascript"
    assert toolchains.normalize("c++") == "cpp"
    assert toolchains.normalize("py") == "python"
    assert toolchains.get_spec("Py")["name"] == "python"
    assert toolchains.get_spec("TS")["name"] == "typescript"
    with pytest.raises(KeyError):
        toolchains.get_spec("not-a-real-language")


def test_plan_uses_argv_without_a_shell():
    plan = toolchains.plan("python", "run", target="main.py", executable="/usr/bin/python3")
    assert plan["shell"] is False
    assert plan["steps"] == [["/usr/bin/python3", "-B", "main.py"]]
    compiled = toolchains.plan("c", "run", target="main.c", executable="/usr/bin/gcc")
    assert compiled["steps"][-1] == ["<temporary-build-dir>/program"]


def test_plan_and_safe_relative_reject_escapes():
    for target in (
        "../evil.py", "/etc/passwd", ".git/config", ".agent/x.py",
        r"C:\Windows\win.ini", r"\Windows\win.ini", "C:relative",
    ):
        with pytest.raises(ValueError):
            toolchains.safe_relative(target)


def test_capability_with_injected_toolchain():
    def fake_which(name):
        return "/fake/python3" if name == "python3" else None

    def fake_run(argv, cwd, timeout=5):
        assert argv[0] == "/fake/python3"
        return {"stdout": "Python 3.12.0", "stderr": "", "exit_code": 0}

    python = toolchains.capability("python", which=fake_which, run=fake_run, use_cache=False)
    assert python["installed"] is True
    assert python["version"] == "Python 3.12.0"
    c_actions = toolchains.capability(
        "c", which=lambda name: "/usr/bin/gcc",
        run=lambda argv, cwd, timeout=5: {"stdout": "gcc 13", "stderr": "", "exit_code": 0},
        use_cache=False,
    )["actions"]
    assert c_actions == ["check", "run"]
    rust = toolchains.capability("rust", which=lambda name: None, run=fake_run, use_cache=False)
    assert rust["installed"] is False
    assert "rustup" in rust["install_hint"]


def test_execute_python_check_and_run(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text('print("hello toolchain")\n', encoding="utf-8")
    check = toolchains.execute("python", "check", root, target="main.py")
    assert check["passed"] is True
    assert check["shell"] is False
    run = toolchains.execute("python", "run", root, target="main.py")
    assert run["passed"] is True
    assert "hello toolchain" in run["steps"][-1]["stdout"]


@pytest.mark.skipif(not shutil.which("gcc"), reason="gcc is not installed")
def test_execute_compiles_and_runs_c(tmp_path):
    root = tmp_path / "c-project"
    root.mkdir()
    (root / "main.c").write_text(
        '#include <stdio.h>\nint main(void){puts("hello c");return 0;}\n', encoding="utf-8")
    run = toolchains.execute("c", "run", root, target="main.c")
    assert run["passed"] is True
    assert "hello c" in run["steps"][-1]["stdout"]


def test_timeout_is_bounded_and_reported(tmp_path):
    result = toolchains.run_argv(["python3", "-c", "import time; time.sleep(5)"],
                                 tmp_path, timeout=1)
    assert result["timed_out"] is True
    assert result["exit_code"] != 0


def test_clean_env_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", "super-secret-token")
    monkeypatch.setenv("MODEL_API_KEY", "provider-secret")
    env = toolchains.clean_env()
    assert "AGENT_ADMIN_TOKEN" not in env
    assert "MODEL_API_KEY" not in env
    assert toolchains.clean_env({"EXTRA": "1"})["EXTRA"] == "1"


def test_project_detection_ignores_dependency_directories(tmp_path):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "app.py").write_text("print(1)\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("assert True\n", encoding="utf-8")
    (root / "node_modules" / "bundle.js").write_text("var x=1\n", encoding="utf-8")
    (root / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    breakdown = toolchains.project_languages(root)
    languages = {item["language"]: item["files"] for item in breakdown["languages"]}
    assert languages["python"] == 2
    assert languages["rust"] == 1
    assert "javascript" not in languages
    assert breakdown["total_coded_files"] >= 4


def test_custom_language_registration_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYGLOT_TOOLCHAINS_PATH", str(tmp_path / "toolchains.json"))
    toolchains.reset_cache()
    defined = toolchains.register_custom({
        "language": "mylang", "extensions": [".ml2"],
        "probes": [["python3", "--version"]],
        "run": ["{exe}", "{file}"], "install": "Install my interpreter",
    })
    assert defined["name"] == "mylang" and defined["custom"] is True
    assert toolchains.custom_path().is_file()
    assert toolchains.identify("sample.ml2") == "mylang"
    info = toolchains.capability("mylang", use_cache=False)
    assert info["installed"] is True
    names = {item["language"] for item in toolchains.report(use_cache=False)["languages"]}
    assert "mylang" in names


def test_invalid_custom_definitions_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYGLOT_TOOLCHAINS_PATH", str(tmp_path / "toolchains.json"))
    cases = [
        {"language": "bad lang!", "probes": [["python3", "--version"]]},
        {"language": "xlang", "probes": [["sh", "-c"]], "extensions": ["py"]},
        {"language": "ylang", "probes": [["python3", "--version"]], "run": ["{exe}", "{unknown}"]},
        {"language": "zlang", "run": ["{exe}", "{file}"]},
    ]
    for case in cases:
        with pytest.raises(ValueError):
            toolchains.register_custom(case)


def test_starter_templates_exist():
    python = toolchains.scaffold("python")
    assert "main.py" in python and "print" in python["main.py"]
    csharp = toolchains.scaffold("csharp")
    assert "Program.cs" in csharp and "hello.csproj" in csharp
    with pytest.raises(KeyError):
        toolchains.scaffold("not-a-real-language")


def test_guess_language():
    assert toolchains.guess_language("build a react dashboard") == "javascript"
    assert toolchains.guess_language("write a rust cli") == "rust"
    assert toolchains.guess_language("add a postgres query") == "sql"
    assert toolchains.guess_language("something vague") == "python"
