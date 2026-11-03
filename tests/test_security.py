"""Security regression tests: auth, brute-force lockout, limits, headers."""
import hashlib
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.api import engine, security
from services.api.main import app

TOKEN = "correct-horse-battery-staple"


@pytest.fixture
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("SECURITY_ENABLED", "1")
    monkeypatch.delenv("AGENT_ADMIN_TOKEN_SHA256", raising=False)
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    security.reset()
    yield
    security.reset()


def test_token_is_compared_by_digest(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    assert security.verify_token("Bearer " + TOKEN)
    assert security.verify_token(TOKEN)
    assert not security.verify_token("Bearer wrong-token")
    assert not security.verify_token("")
    security.authorize("Bearer " + TOKEN)


def test_hashed_secret_supported(clean, monkeypatch):
    monkeypatch.delenv("AGENT_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("AGENT_ADMIN_TOKEN_SHA256", hashlib.sha256(b"hashed-secret").hexdigest())
    assert security.verify_token("hashed-secret")
    assert not security.verify_token("hashed-secrets")
    assert security.token_strength() == "hashed"


def test_unconfigured_token_is_refused(clean, monkeypatch):
    monkeypatch.delenv("AGENT_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_ADMIN_TOKEN_SHA256", raising=False)
    with pytest.raises(HTTPException) as error:
        security.authorize("Bearer anything")
    assert error.value.status_code == 403


def test_lockout_escalates_and_clears(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_MAX_AUTH_FAILURES", "2")
    monkeypatch.setenv("SECURITY_LOCKOUT_BASE_SECONDS", "30")
    monkeypatch.setenv("SECURITY_AUTH_WINDOW_SECONDS", "600")
    security.record_failure("203.0.113.9")
    assert security.lockout_remaining("203.0.113.9") == 0
    security.record_failure("203.0.113.9")
    first = security.lockout_remaining("203.0.113.9")
    assert 0 < first <= 30
    security.clear_failures("203.0.113.9")
    assert security.lockout_remaining("203.0.113.9") == 0
    security.record_failure("203.0.113.9")
    security.record_failure("203.0.113.9")
    assert security.lockout_remaining("203.0.113.9") > first


def test_security_headers_and_csp(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["referrer-policy"] == "no-referrer"
    assert "content-security-policy" in client.get("/").headers
    assert "content-security-policy" not in health.headers
    assert "server" not in health.headers


def test_brute_force_is_throttled_but_correct_token_still_works(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_MAX_AUTH_FAILURES", "2")
    client = TestClient(app)
    url = "/api/projects/demo/history"
    assert client.get(url).status_code == 403
    assert client.get(url, headers={"Authorization": "Bearer nope"}).status_code == 403
    blocked = client.get(url, headers={"Authorization": "Bearer nope"})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    allowed = client.get(url, headers={"Authorization": "Bearer " + TOKEN})
    assert allowed.status_code == 200


def test_origin_and_method_and_body_limits(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_MAX_BODY_BYTES", "512")
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.post("/api/chat", headers={**headers, "Origin": "https://evil.example"},
                       json={"project": "demo", "message": "hello"}).status_code == 403
    assert client.request("DELETE", "/api/chat", headers=headers).status_code == 405
    oversized = client.post("/api/chat", headers=headers,
                            json={"project": "demo", "message": "x" * 4000})
    assert oversized.status_code == 413


def test_encoded_traversal_is_rejected(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    client = TestClient(app)
    response = client.get("/api/%2e%2e/secret", headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 400


def test_rate_limit_returns_retry_after(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_RATE_LIMIT_PER_MINUTE", "2")
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.get("/api/security/status", headers=headers).status_code == 200
    assert client.get("/api/security/status", headers=headers).status_code == 200
    limited = client.get("/api/security/status", headers=headers)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_audit_log_records_failures_without_secrets(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    client = TestClient(app)
    client.get("/api/projects/demo/history", headers={"Authorization": "Bearer leaked-guess"})
    posture = security.status()
    events = [entry["event"] for entry in posture["recent_audit"]]
    assert "auth.failure" in events
    dumped = json.dumps(posture)
    assert TOKEN not in dumped
    assert "leaked-guess" not in dumped
    assert posture["token_configured"] is True


def test_status_endpoint_requires_token(clean, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    client = TestClient(app)
    assert client.get("/api/security/status").status_code == 403
    response = client.get("/api/security/status", headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 200
    assert response.json()["max_auth_failures"] >= 1
