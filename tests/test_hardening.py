"""Defence-in-depth hardening: request integrity, injection, SSRF, audit chain."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from services.api import engine, hardening, security
from services.api.main import app

TOKEN = "correct-horse-battery-staple"
AUTH = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("SECURITY_ENABLED", "1")
    monkeypatch.setenv("HARDENING_ENABLED", "1")
    monkeypatch.setenv("SECURITY_BLOCK_SUSPICIOUS_INPUT", "1")
    monkeypatch.setenv("SECURITY_ENFORCE_HOST", "1")
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("AGENT_ADMIN_TOKEN_SHA256", raising=False)
    monkeypatch.delenv("AGENT_TOTP_SECRET", raising=False)
    monkeypatch.delenv("SECURITY_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("SECURITY_AUDIT_KEY", raising=False)
    monkeypatch.setattr(engine, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(engine, "DB", tmp_path / "agent.sqlite3")
    security.reset()
    yield tmp_path
    security.reset()


class _HeaderRequest:
    def __init__(self, pairs):
        self.headers = Headers(raw=[(name.encode(), value.encode()) for name, value in pairs])


def test_request_integrity_rejects_smuggling_framing():
    assert hardening.request_integrity(_HeaderRequest([
        ("content-length", "5"), ("transfer-encoding", "chunked")]))
    assert hardening.request_integrity(_HeaderRequest([
        ("content-length", "5"), ("content-length", "6")]))
    assert hardening.request_integrity(_HeaderRequest([
        ("transfer-encoding", "gzip")]))
    assert hardening.request_integrity(_HeaderRequest([
        ("x-test", "value\r\nInjected: 1")]))
    assert hardening.request_integrity(_HeaderRequest([("content-length", "12")])) is None
    too_many = [("x-test-%d" % index, "1") for index in range(hardening.MAX_HEADERS + 1)]
    assert hardening.request_integrity(_HeaderRequest(too_many))


def test_host_allowlist_blocks_dns_rebinding(clean):
    assert hardening.host_allowed("localhost:8000")
    assert hardening.host_allowed("[::1]:8000")
    assert hardening.host_allowed("testserver")
    assert not hardening.host_allowed("evil.example")
    client = TestClient(app)
    response = client.get("/api/security/status",
                          headers={**AUTH, "Host": "evil.example"})
    assert response.status_code == 421


def test_configured_host_is_allowed(clean, monkeypatch):
    monkeypatch.setenv("SECURITY_ALLOWED_HOSTS", "*.example.test, api.example.test")
    assert hardening.host_allowed("preview.example.test")
    assert hardening.host_allowed("api.example.test")
    assert not hardening.host_allowed("api.example.test.evil")


def test_content_type_and_cross_site_writes_are_refused(clean):
    client = TestClient(app)
    body = json.dumps({"project": "demo", "message": "hello"})
    wrong_type = client.post("/api/chat", content=body,
                             headers={**AUTH, "Content-Type": "text/plain"})
    assert wrong_type.status_code == 415
    cross_site = client.post("/api/chat", json={"project": "demo", "message": "hello"},
                             headers={**AUTH, "Sec-Fetch-Site": "cross-site"})
    assert cross_site.status_code == 403


def test_structured_injection_is_blocked(clean):
    client = TestClient(app)
    sql = client.get("/api/security/status?limit=1%20UNION%20SELECT%20password%20FROM%20users",
                     headers=AUTH)
    assert sql.status_code == 400
    # A query parameter whose name is also a free-text field name must not
    # become an inspection bypass.
    named_query = client.get(
        "/api/security/status?query=1%20UNION%20SELECT%20password", headers=AUTH)
    assert named_query.status_code == 400
    body = client.post("/api/chat", headers=AUTH,
                       json={"project": "demo'; DROP TABLE messages;--", "message": "hi"})
    assert body.status_code == 400
    traversal = client.post("/api/studio/read", headers=AUTH,
                            json={"project": "demo", "path": "../../etc/passwd"})
    assert traversal.status_code in (400, 403)


def test_free_text_code_is_not_blocked(clean, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_MODEL_ONLY", raising=False)
    client = TestClient(app)
    response = client.post("/api/chat", headers=AUTH, json={
        "project": "demo",
        "message": "Explain '<script>alert(1)</script>' and SELECT * FROM users",
    })
    assert response.status_code == 200
    assert "security policy" not in response.text.lower()


def test_ssrf_guard_blocks_private_and_metadata_targets():
    assert hardening.url_problem("http://127.0.0.1:8000/")
    assert hardening.url_problem("http://169.254.169.254/latest/meta-data/")
    assert hardening.url_problem("http://10.0.0.5/")
    assert hardening.url_problem("http://192.168.1.1/")
    assert hardening.url_problem("http://[::1]/")
    assert hardening.url_problem("http://[::ffff:127.0.0.1]/")
    assert hardening.url_problem("file:///etc/passwd")
    assert hardening.url_problem("http://user:pass@93.184.216.34/")
    assert hardening.url_problem("http://93.184.216.34/") is None
    assert hardening.url_problem("http://127.0.0.1:8000/", allow_loopback=True) is None


def test_audit_chain_detects_tampering(clean):
    security.audit("test.one", "first")
    security.audit("test.two", "second")
    verified = security.verify_audit_chain()
    assert verified["ok"] is True
    assert verified["checked"] == 2
    database = clean / "security.sqlite3"
    with sqlite3.connect(database) as con:
        con.execute("UPDATE audit_log SET detail='tampered' WHERE event='test.two'")
    tampered = security.verify_audit_chain()
    assert tampered["ok"] is False


def test_global_cooldown_stops_distributed_guessing(clean, monkeypatch):
    monkeypatch.setenv("SECURITY_GLOBAL_FAILURE_LIMIT", "3")
    monkeypatch.setenv("SECURITY_GLOBAL_COOLDOWN_SECONDS", "30")
    for index in range(3):
        security.record_failure(f"198.51.100.{index}")
    assert security.global_cooldown_remaining() > 0
    client = TestClient(app)
    blocked = client.get("/api/projects/demo/history")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    allowed = client.get("/api/projects/demo/history", headers=AUTH)
    assert allowed.status_code == 200


def test_egress_budget_limits_bulk_export(clean, monkeypatch):
    monkeypatch.setenv("SECURITY_EGRESS_BYTES_PER_MINUTE", "1000")
    hardening.note_egress("203.0.113.7", 1200)
    assert hardening.egress_retry("203.0.113.7") > 0
    assert hardening.egress_retry("203.0.113.8") == 0


def test_coverage_matrix_and_status(clean):
    assert len(hardening.THREATS) == 50
    assert {item["id"] for item in hardening.THREATS} == set(range(1, 51))
    assert len({item["category"] for item in hardening.THREATS}) == 10
    assert all(item["controls"] for item in hardening.THREATS)
    client = TestClient(app)
    assert client.get("/api/security/coverage").status_code == 403
    response = client.get("/api/security/coverage", headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["threats"]) == 50
    assert payload["summary"]["threats_tracked"] == 50
    status = client.get("/api/security/status", headers=AUTH).json()
    assert status["hardening"]["threats_tracked"] == 50
    assert status["audit_chain"]["ok"] is True
    assert "recent_audit" in status


def test_static_mounts_do_not_expose_protected_directories():
    assert hardening.static_mount_problems(app) == []


def test_framing_requires_length_and_rejects_chunked():
    from starlette.datastructures import URL

    class FrameRequest:
        method = "POST"
        url = URL("http://testserver/api/chat")

        def __init__(self, pairs):
            self.headers = Headers(raw=[(name.encode(), value.encode())
                                        for name, value in pairs])

    assert hardening.framing_problem(FrameRequest([]))
    assert hardening.framing_problem(FrameRequest([("transfer-encoding", "chunked")]))
    assert hardening.framing_problem(FrameRequest([("content-length", "12")])) is None


def test_outbound_integrations_use_the_ssrf_guard(clean, monkeypatch):
    from services.api import agenticseek, local_model

    monkeypatch.setenv("LOCAL_MODEL_BASE_URL", "http://10.0.0.9/v1")
    with pytest.raises(ValueError):
        local_model.local_url()
    monkeypatch.setenv("AGENTICSEEK_URL", "http://10.0.0.9")
    monkeypatch.setenv("AGENTICSEEK_API_TOKEN", "token")
    with pytest.raises(agenticseek.AgenticSeekUnavailable):
        agenticseek.config()
