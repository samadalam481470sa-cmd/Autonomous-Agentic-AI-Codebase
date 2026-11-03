"""Optional TOTP two-factor authentication for the administrator token."""
import pytest
from fastapi.testclient import TestClient

from services.api import engine, security
from services.api.main import app

TOKEN = "correct-horse-battery-staple"
# RFC 6238 test secret: ASCII "12345678901234567890".
SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


@pytest.fixture
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("AGENT_TOTP_SECRET", raising=False)
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    security.reset()
    return tmp_path


def test_rfc6238_reference_vector(clean):
    assert security.totp_code(SECRET, 1) == "287082"


def test_mfa_challenge_then_success(clean, monkeypatch):
    monkeypatch.setenv("AGENT_TOTP_SECRET", SECRET)
    assert security.mfa_configured()
    client = TestClient(app)
    url = "/api/projects/demo/history"
    headers = {"Authorization": "Bearer " + TOKEN}
    assert client.get(url, headers=headers).status_code == 401
    assert client.get(url, headers={**headers, "X-Agent-TOTP": "12345"}).status_code == 401
    code = security.current_totp()
    assert client.get(url, headers={**headers, "X-Agent-TOTP": code}).status_code == 200
    # The same code is accepted again inside its 30-second step; guessing is
    # still bounded by the failure ledger and rate limits.
    assert client.get(url, headers={**headers, "X-Agent-TOTP": code}).status_code == 200


def test_invalid_mfa_configuration_does_not_lock_the_operator_out(clean, monkeypatch):
    monkeypatch.setenv("AGENT_TOTP_SECRET", "not-valid-base32!!")
    assert not security.mfa_configured()
    client = TestClient(app)
    response = client.get("/api/projects/demo/history",
                          headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 200


def test_invalid_code_is_counted_as_auth_failure(clean, monkeypatch):
    monkeypatch.setenv("AGENT_TOTP_SECRET", SECRET)
    monkeypatch.setenv("SECURITY_MAX_AUTH_FAILURES", "2")
    client = TestClient(app)
    url = "/api/projects/demo/history"
    headers = {"Authorization": "Bearer " + TOKEN, "X-Agent-TOTP": "999999"}
    assert client.get(url, headers=headers).status_code == 401
    assert client.get(url, headers=headers).status_code == 401
    blocked = client.get(url, headers=headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1


def test_status_reports_mfa_configuration(clean, monkeypatch):
    monkeypatch.setenv("AGENT_TOTP_SECRET", SECRET)
    posture = security.status()
    assert posture["mfa_enabled"] is True
    assert posture["mfa_header"] == "X-Agent-TOTP"
    assert SECRET not in str(posture)
