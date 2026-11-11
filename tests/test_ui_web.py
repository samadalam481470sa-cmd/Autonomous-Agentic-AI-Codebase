from pathlib import Path

from fastapi.testclient import TestClient

from services.api.main import app

ROOT = Path(__file__).resolve().parents[1]
CLIENT = TestClient(app)


def test_tokens_and_sprite_are_served_by_the_app():
    tokens = CLIENT.get("/ui/tokens.css")
    assert tokens.status_code == 200
    assert tokens.headers["content-type"].startswith("text/css")
    assert "--ag-bg-canvas" in tokens.text
    assert "--ag-text-primary" in tokens.text

    sprite = CLIENT.get("/ui/icons.svg")
    assert sprite.status_code == 200
    assert sprite.headers["content-type"].startswith("image/svg+xml")
    assert '<symbol id="ag-spark"' in sprite.text
    assert 'stroke="currentColor"' in sprite.text

    favicon = CLIENT.get("/ui/favicon.svg")
    assert favicon.status_code == 200
    assert "<svg" in favicon.text


def test_both_pages_use_the_first_party_design_system():
    for route in ("/", "/studio"):
        response = CLIENT.get(route)
        assert response.status_code == 200
        html = response.text
        assert "/ui/tokens.css" in html
        assert "/ui/icons.svg#ag-spark" in html or "/ui/icons.svg#ag-terminal" in html
        assert 'data-theme="dark"' in html
        assert 'id="theme"' in html


def test_app_surfaces_implemented_workspace_features():
    home = CLIENT.get("/").text
    studio = CLIENT.get("/studio").text

    assert "/api/projects/plan" in home
    assert 'fetch("/api/projects"' in home
    assert 'href="/docs"' in home

    assert 'rootApi("index/refresh"' in studio
    assert 'rootApi("index/search"' in studio
    assert 'rootApi("learning/feedback"' in studio
    assert 'rootApi("learning/evaluation"' in studio
    assert 'href="/docs"' in studio


def test_packaging_includes_the_ui_package():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    backend = (ROOT / "scripts" / "build_backend.py").read_text(encoding="utf-8")
    assert "COPY packages ./packages" in dockerfile
    assert "packages/ui" in backend
    assert (ROOT / "packages" / "ui" / "tokens.css").is_file()
    assert (ROOT / "packages" / "ui" / "icons.svg").is_file()
