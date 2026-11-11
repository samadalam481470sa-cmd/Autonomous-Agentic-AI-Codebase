"""Repository diagrams: import resolution, escaped output and API auth."""
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from services.api import diagrams, engine, security
from services.api.main import app

TOKEN = "diagram-test-token-123456789"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    security.reset()
    root = engine.workspace("demo")
    (root / "app").mkdir(parents=True)
    (root / "app" / "models.py").write_text(
        "class Invoice:\n    pass\n", encoding="utf-8"
    )
    (root / "app" / "main.py").write_text(
        "from .models import Invoice\n\n"
        "def create_invoice():\n    return Invoice()\n",
        encoding="utf-8",
    )
    (root / "web").mkdir()
    (root / "web" / "util.js").write_text(
        "export const format = (value) => String(value);\n", encoding="utf-8"
    )
    (root / "web" / "app.js").write_text(
        "import { format } from './util.js';\nconsole.log(format(42));\n",
        encoding="utf-8",
    )
    return root


def test_diagram_resolves_in_project_imports(project):
    result = diagrams.build("demo", max_nodes=20)
    pairs = {(edge["source"], edge["target"]) for edge in result["edges"]}
    assert ("app/main.py", "app/models.py") in pairs
    assert ("web/app.js", "web/util.js") in pairs
    assert "flowchart LR" in result["mermaid"]
    assert result["stats"]["files_shown"] == 4
    assert result["svg"].startswith("<svg")


def test_svg_is_well_formed_and_escaped(project):
    result = diagrams.build("demo")
    ElementTree.fromstring(result["svg"])
    assert "&lt;" not in result["svg"]
    assert "app/main.py" in result["svg"]


def test_empty_project_returns_valid_svg(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    engine.workspace("empty")
    result = diagrams.build("empty")
    assert result["nodes"] == []
    assert "No supported source files" in result["svg"]
    ElementTree.fromstring(result["svg"])


def test_diagram_endpoint_requires_auth(project):
    headers = {"Authorization": "Bearer " + TOKEN}
    client = TestClient(app)
    assert client.post("/api/diagrams/architecture", json={"project": "demo"}).status_code == 403
    response = client.post(
        "/api/diagrams/architecture", json={"project": "demo"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["stats"]["edges"] >= 2
