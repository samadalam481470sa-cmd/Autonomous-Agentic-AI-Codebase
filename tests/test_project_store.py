from services.api import project_store
from fastapi import HTTPException
import pytest

def test_project_creation_and_uniqueness(tmp_path,monkeypatch):
    monkeypatch.setenv("PROJECT_DB_PATH",str(tmp_path/"projects.sqlite3"))
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-secret")
    result=project_store.create(project_store.NewProject(slug="demo",title="Demo"),"Bearer test-secret")
    assert result["slug"]=="demo"
    assert project_store.list_projects("Bearer test-secret")["projects"][0]["id"]==result["id"]
    with pytest.raises(HTTPException) as error:
        project_store.create(project_store.NewProject(slug="demo",title="Duplicate"),"Bearer test-secret")
    assert error.value.status_code==409

def test_requires_auth(tmp_path,monkeypatch):
    monkeypatch.setenv("PROJECT_DB_PATH",str(tmp_path/"projects.sqlite3"))
    monkeypatch.setenv("AGENT_ADMIN_TOKEN","test-secret")
    with pytest.raises(HTTPException) as error:project_store.list_projects(None)
    assert error.value.status_code==403
