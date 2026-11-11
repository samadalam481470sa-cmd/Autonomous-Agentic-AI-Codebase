"""Safe public-GitHub ingestion into the local retrieval index."""
import io
import tarfile
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from services.api import engine, github_learning, security
from services.api.main import app

TOKEN = "github-learning-token-123456789"


def archive(files, root="demo-abc1234"):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for path, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(f"{root}/{path}")
            info.size = len(data)
            info.mtime = int(time.time())
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def fake_client(archive_bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json={"default_branch": "main", "license": {"spdx_id": "MIT"}},
            )
        if request.url.host == "codeload.github.com":
            return httpx.Response(200, content=archive_bytes)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("GITHUB_LEARNING", "1")
    monkeypatch.setenv("GITHUB_DB_PATH", str(tmp_path / "github.sqlite3"))
    monkeypatch.setenv("SEMANTIC_DIM", "64")
    monkeypatch.setenv("SEMANTIC_RAG", "0")
    security.reset()
    return tmp_path


def test_learn_public_repository_and_search(project, monkeypatch):
    payload = archive({
        "src/invoice.py": "def calculate_invoice_total(items):\n    return sum(items)\n",
        "README.md": "# Demo\n\nInvoice utilities.\n",
        "LICENSE": "MIT\n",
    })
    monkeypatch.setattr(github_learning, "_client", lambda: fake_client(payload))

    result = github_learning.learn("https://github.com/alice/demo.git")
    source = result["source"]
    assert source["repo"] == "alice/demo"
    assert source["license"] == "MIT"
    assert source["project"].startswith("gh_alice_demo_")
    assert source["files"] == 3
    assert result["index"]["embedded_files"] == 2  # LICENSE has no source suffix

    matches = github_learning.search_endpoint(
        github_learning.SearchRequest(query="invoice total"),
        authorization="Bearer " + TOKEN,
    )
    assert matches["results"]
    assert matches["results"][0]["repo"] == "alice/demo"
    assert github_learning.list_sources()[0]["project"] == source["project"]


def test_learning_is_disabled_by_default(project, monkeypatch):
    monkeypatch.setenv("GITHUB_LEARNING", "0")
    with pytest.raises(github_learning.HTTPException) as error:
        github_learning.learn("alice/demo")
    assert error.value.status_code == 503


def test_tar_path_traversal_is_rejected(project, monkeypatch):
    payload = archive({"../escape.py": "print('no')\n"})
    monkeypatch.setattr(github_learning, "_client", lambda: fake_client(payload))
    with pytest.raises(github_learning.HTTPException) as error:
        github_learning.learn("alice/demo")
    assert error.value.status_code == 400
    assert "traversal" in str(error.value.detail).lower()
    assert not (project / "escape.py").exists()


def test_invalid_repository_is_rejected_without_network(project, monkeypatch):
    called = False

    def should_not_run():
        nonlocal called
        called = True
        raise AssertionError("network should not be touched")

    monkeypatch.setattr(github_learning, "_client", should_not_run)
    with pytest.raises(github_learning.HTTPException) as error:
        github_learning.learn("https://evil.example/repo")
    assert error.value.status_code == 400
    assert called is False


def test_github_endpoints_require_auth(project, monkeypatch):
    payload = archive({"src/app.py": "def app():\n    return 1\n"})
    monkeypatch.setattr(github_learning, "_client", lambda: fake_client(payload))
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.get("/api/github/sources").status_code == 403
    learned = client.post(
        "/api/github/learn", json={"repo": "alice/demo"}, headers=headers
    )
    assert learned.status_code == 200
    listed = client.get("/api/github/sources", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["sources"][0]["project"] == learned.json()["source"]["project"]
