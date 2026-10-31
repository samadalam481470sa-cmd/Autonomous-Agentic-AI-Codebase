import pytest
from services.api import engine
def test_workspace_containment(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    assert engine.safe_path("demo","a.txt")==tmp_path/"demo"/"a.txt"
    with pytest.raises(ValueError): engine.safe_path("demo","../outside")
    with pytest.raises(ValueError): engine.workspace("../bad")
def test_file_roundtrip(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    assert "Wrote" in engine.tool("demo","write_file",{"path":"src/app.py","content":"hello world"})
    assert engine.tool("demo","read_file",{"path":"src/app.py"})=="hello world"
    assert "src/app.py" in engine.tool("demo","list_files",{})
    assert "hello world" in engine.tool("demo","search_files",{"query":"hello"})
def test_commands_disabled(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"ROOT",tmp_path)
    monkeypatch.delenv("ALLOW_COMMANDS",raising=False)
    assert "disabled" in engine.tool("demo","run_command",{"command":"echo hello"})
def test_persistence(tmp_path,monkeypatch):
    monkeypatch.setattr(engine,"DB",tmp_path/"db.sqlite")
    engine.save("demo","user","hello")
    assert engine.history("demo")==[{"role":"user","content":"hello"}]
