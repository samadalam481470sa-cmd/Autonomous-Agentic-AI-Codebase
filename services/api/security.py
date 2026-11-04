"""Authentication, brute-force defence, rate limiting and HTTP hardening.

The service is single-process and local-first, so the controls here are
dependency-free: an in-memory sliding-window limiter for throughput, plus a
small SQLite ledger for failed authentication attempts, exponential lockouts
and an append-only audit trail. Tokens are compared as SHA-256 digests in
constant time and are never written to logs or the audit trail.

A correct token is always accepted while an address is locked out; lockouts
therefore throttle guessing without letting an attacker deny service to the
real operator.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import struct
import threading
import time
import uuid
from collections import deque
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

ALLOWED_METHODS = {"GET", "HEAD", "POST", "OPTIONS"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_TOKEN_CHARS = 4096
_LOCK = threading.RLock()
_WINDOWS: dict[tuple[str, str], deque] = {}
MAX_WINDOWS = 10000

# Stricter buckets for expensive or security-sensitive endpoint families.
RATE_BUCKETS = {
    "/api/ai": ("SECURITY_AI_RATE_LIMIT_PER_MINUTE", 60),
    "/api/agents": ("SECURITY_AGENTS_RATE_LIMIT_PER_MINUTE", 30),
    "/api/device": ("SECURITY_DEVICE_RATE_LIMIT_PER_MINUTE", 120),
    "/api/chat": ("SECURITY_CHAT_RATE_LIMIT_PER_MINUTE", 40),
    "/api/agent": ("SECURITY_AGENT_RATE_LIMIT_PER_MINUTE", 30),
    "/api/polyglot": ("SECURITY_POLYGLOT_RATE_LIMIT_PER_MINUTE", 30),
    "/api/worker": ("SECURITY_WORKER_RATE_LIMIT_PER_MINUTE", 60),
    "/api/learning": ("SECURITY_LEARNING_RATE_LIMIT_PER_MINUTE", 60),
    "/api/execution": ("SECURITY_EXECUTION_RATE_LIMIT_PER_MINUTE", 20),
    "/api/integrations": ("SECURITY_INTEGRATION_RATE_LIMIT_PER_MINUTE", 20),
}


def enabled() -> bool:
    return os.getenv("SECURITY_ENABLED", "1") != "0"


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def max_failures() -> int:
    return _int("SECURITY_MAX_AUTH_FAILURES", 5, 1, 100)


def failure_window() -> int:
    return _int("SECURITY_AUTH_WINDOW_SECONDS", 300, 10, 86400)


def lockout_base() -> int:
    return _int("SECURITY_LOCKOUT_BASE_SECONDS", 60, 1, 86400)


def lockout_cap() -> int:
    return _int("SECURITY_LOCKOUT_MAX_SECONDS", 900, 1, 604800)


def max_body_bytes() -> int:
    return _int("SECURITY_MAX_BODY_BYTES", 2 * 1024 * 1024, 1024, 64 * 1024 * 1024)


def general_rate_limit() -> int:
    return _int("SECURITY_RATE_LIMIT_PER_MINUTE", 300, 1, 100000)


def reset() -> None:
    """Clear in-memory limiter state. Test-only; the audit ledger is untouched."""
    with _LOCK:
        _WINDOWS.clear()


def _db_path() -> Path:
    path = Path(os.getenv("SECURITY_DB_PATH", "./database/security.sqlite3")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """CREATE TABLE IF NOT EXISTS auth_state(
        identifier TEXT PRIMARY KEY,
        failures INTEGER NOT NULL DEFAULT 0,
        first_failure_at INTEGER NOT NULL DEFAULT 0,
        strikes INTEGER NOT NULL DEFAULT 0,
        locked_until INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER NOT NULL,
        event TEXT NOT NULL,
        actor TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        request_id TEXT NOT NULL DEFAULT '')"""
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC,id DESC)")
    return con


def audit(event: str, detail: str = "", actor: str = "", request_id: str = "") -> None:
    """Best-effort append-only audit entry. Never raises into a request."""
    try:
        with _LOCK, closing(_connect()) as con, con:
            con.execute(
                "INSERT INTO audit_log(created_at,event,actor,detail,request_id) VALUES(?,?,?,?,?)",
                (int(time.time()), str(event)[:64], str(actor)[:128],
                 str(detail)[:1000], str(request_id)[:64]),
            )
            con.execute(
                "DELETE FROM audit_log WHERE id NOT IN "
                "(SELECT id FROM audit_log ORDER BY id DESC LIMIT 2000)"
            )
    except (sqlite3.Error, OSError, ValueError):
        return


def token_digest() -> str | None:
    """Expected token digest. A pre-hashed secret can replace the plaintext."""
    prehashed = os.getenv("AGENT_ADMIN_TOKEN_SHA256", "").strip().lower()
    if prehashed:
        if len(prehashed) == 64 and all(c in "0123456789abcdef" for c in prehashed):
            return prehashed
        return None
    raw = os.getenv("AGENT_ADMIN_TOKEN", "")
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def token_configured() -> bool:
    return token_digest() is not None


def token_fingerprint() -> str | None:
    digest = token_digest()
    return None if digest is None else digest[:12]


def token_strength() -> str:
    raw = os.getenv("AGENT_ADMIN_TOKEN", "")
    if os.getenv("AGENT_ADMIN_TOKEN_SHA256", "").strip():
        return "hashed"
    if len(raw) < 12:
        return "weak"
    if len(raw) < 24:
        return "moderate"
    return "strong"


def strip_scheme(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def verify_token(value: str | None) -> bool:
    expected = token_digest()
    if expected is None:
        return False
    candidate = strip_scheme(value)
    if not candidate or len(candidate) > MAX_TOKEN_CHARS:
        return False
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected)


def request_token(headers) -> str | None:
    return headers.get("authorization") or headers.get("x-agent-token")


def totp_secret() -> str:
    return os.getenv("AGENT_TOTP_SECRET", "").strip()


def _totp_key(secret: str | None = None) -> bytes:
    import base64

    normalized = re.sub(r"[\s-]", "", (secret or totp_secret())).upper()
    if not normalized:
        raise ValueError("no TOTP secret")
    padded = normalized + "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    if len(key) < 10:
        raise ValueError("TOTP secret is too short")
    return key


def mfa_configured() -> bool:
    try:
        _totp_key()
    except (ValueError, TypeError, UnicodeError):
        return False
    return True


def totp_code(secret: str | None, counter: int, digits: int = 6) -> str:
    """RFC 6238 TOTP (SHA-1, 30-second step) generated with the stdlib."""
    digest = hmac.new(_totp_key(secret), struct.pack(">Q", int(counter)), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def current_totp(at: float | None = None) -> str:
    counter = int(at if at is not None else time.time()) // 30
    return totp_code(None, counter)


def verify_totp(value: str | None, at: float | None = None, window: int = 1) -> bool:
    """Check a six-digit code against the current step and one step either side."""
    if not mfa_configured():
        return False
    code = re.sub(r"\D", "", value or "")
    if len(code) != 6:
        return False
    counter = int(at if at is not None else time.time()) // 30
    for offset in range(-max(0, window), max(0, window) + 1):
        if counter + offset < 0:
            continue
        if hmac.compare_digest(code, totp_code(None, counter + offset)):
            return True
    return False


def authorize(value: str | None, scope: str = "admin") -> None:
    """Shared administrator check used by every API router."""
    if not token_configured():
        audit("auth.unconfigured", "AGENT_ADMIN_TOKEN is not set")
        raise HTTPException(403, "Administrator token required; set AGENT_ADMIN_TOKEN")
    if not verify_token(value):
        audit("auth.failure", "invalid token for scope " + scope)
        raise HTTPException(403, "Administrator token required")
    if token_strength() == "weak":
        audit("auth.weak_token", "AGENT_ADMIN_TOKEN is shorter than 12 characters")


def client_ip(request) -> str:
    trust_proxy = os.getenv("SECURITY_TRUST_PROXY", "0") == "1"
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        candidate = forwarded.split(",")[0].strip()
        if candidate and len(candidate) <= 64:
            return candidate
    client = getattr(request, "client", None)
    return (getattr(client, "host", None) or "unknown")[:64]


def lockout_remaining(identifier: str) -> int:
    try:
        with closing(_connect()) as con:
            row = con.execute(
                "SELECT locked_until FROM auth_state WHERE identifier=?", (identifier,)
            ).fetchone()
    except (sqlite3.Error, OSError):
        return 0
    if row is None:
        return 0
    remaining = int(row["locked_until"]) - int(time.time())
    if remaining <= 0:
        return 0
    return remaining


def record_failure(identifier: str) -> int:
    """Count one failed authentication and escalate the lockout. Returns seconds."""
    now = int(time.time())
    window = failure_window()
    locked_until = 0
    try:
        with _LOCK, closing(_connect()) as con, con:
            row = con.execute(
                "SELECT failures,first_failure_at,strikes,locked_until FROM auth_state WHERE identifier=?",
                (identifier,),
            ).fetchone()
            if row is None or now - int(row["first_failure_at"]) > window:
                failures, first, strikes = 1, now, (0 if row is None else int(row["strikes"]))
            else:
                failures, first, strikes = int(row["failures"]) + 1, int(row["first_failure_at"]), int(row["strikes"])
            if failures >= max_failures():
                strikes = min(strikes + 1, 16)
                locked_until = now + min(lockout_base() * (2 ** (strikes - 1)), lockout_cap())
            con.execute(
                """INSERT INTO auth_state(identifier,failures,first_failure_at,strikes,locked_until,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(identifier) DO UPDATE SET
                failures=excluded.failures,first_failure_at=excluded.first_failure_at,
                strikes=excluded.strikes,locked_until=excluded.locked_until,updated_at=excluded.updated_at""",
                (identifier, failures, first, strikes, locked_until, now),
            )
    except (sqlite3.Error, OSError):
        return 0
    if locked_until:
        audit("auth.lockout", f"address locked for {locked_until - now}s", actor=identifier)
        return locked_until - now
    return 0


def clear_failures(identifier: str) -> None:
    try:
        with _LOCK, closing(_connect()) as con, con:
            con.execute(
                "UPDATE auth_state SET failures=0,locked_until=0,updated_at=? WHERE identifier=?",
                (int(time.time()), identifier),
            )
    except (sqlite3.Error, OSError):
        return


def rate_limit(identifier: str, bucket: str, limit: int, window: int = 60) -> int:
    """Sliding-window limiter. Returns 0 when allowed, else seconds to retry."""
    if limit <= 0:
        return 0
    now = time.monotonic()
    key = (bucket, identifier)
    with _LOCK:
        if len(_WINDOWS) > MAX_WINDOWS:
            for stale in [k for k, q in _WINDOWS.items() if not q or now - q[-1] > window]:
                _WINDOWS.pop(stale, None)
        window_queue = _WINDOWS.setdefault(key, deque())
        while window_queue and now - window_queue[0] > window:
            window_queue.popleft()
        if len(window_queue) >= limit:
            return max(1, int(window - (now - window_queue[0])) + 1)
        window_queue.append(now)
    return 0


def rate_limit_for_path(path: str, identifier: str) -> int:
    retry = rate_limit(identifier, "general", general_rate_limit())
    if retry:
        return retry
    for prefix, (env_name, default) in RATE_BUCKETS.items():
        if path.startswith(prefix):
            limit = _int(env_name, default, 1, 100000)
            return rate_limit(identifier, prefix, limit)
    return 0


def origin_allowed(request) -> bool:
    origin = request.headers.get("origin", "")
    if not origin:
        return True
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    configured = {item.strip().lower() for item in os.getenv("SECURITY_ALLOWED_ORIGINS", "").split(",") if item.strip()}
    if origin.lower() in configured:
        return True
    host = request.headers.get("host", "").lower()
    if host and parsed.netloc.lower() == host:
        return True
    return (parsed.hostname or "") in LOOPBACK_HOSTS


def suspicious_target(request) -> bool:
    raw = request.scope.get("raw_path") or b""
    lowered = raw.lower()
    if b"\x00" in raw or b"%00" in lowered:
        return True
    if b".." in raw or b"%2e%2e" in lowered or b"%252e" in lowered:
        return True
    return request.headers.get("x-http-method-override") is not None


def harden_headers(response, request) -> None:
    headers = response.headers
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "no-referrer"
    headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(self), payment=()"
    headers["Cross-Origin-Opener-Policy"] = "same-origin"
    headers["Cross-Origin-Resource-Policy"] = "same-origin"
    headers["X-Permitted-Cross-Domain-Policies"] = "none"
    headers["X-Request-ID"] = getattr(request.state, "request_id", "")
    content_type = headers.get("content-type", "")
    if content_type.startswith("text/html"):
        headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
            "frame-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        headers["Cache-Control"] = "no-store"
    elif request.url.path.startswith("/api/"):
        headers["Cache-Control"] = "no-store"
        headers["Pragma"] = "no-cache"
    if request.url.scheme == "https":
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    try:
        del headers["server"]
    except KeyError:
        pass


def reject(status: int, detail: str, request, retry_after: int | None = None) -> JSONResponse:
    response = JSONResponse({"detail": detail}, status_code=status)
    if retry_after is not None:
        response.headers["Retry-After"] = str(max(1, int(retry_after)))
    response.headers["X-Request-ID"] = getattr(request.state, "request_id", "")
    harden_headers(response, request)
    return response


def _valid_body_limit(request) -> int | None:
    header = request.headers.get("content-length")
    if header is None:
        return None
    try:
        length = int(header)
    except ValueError:
        return -1
    if length < 0:
        return -1
    if length > max_body_bytes():
        return max_body_bytes()
    return None


class SecurityMiddleware(BaseHTTPMiddleware):
    """Applies hardening to every request and brute-force limits to the API."""

    async def dispatch(self, request, call_next):
        if not enabled():
            return await call_next(request)

        request.state.request_id = uuid.uuid4().hex
        path = request.url.path
        api_path = path.startswith("/api/")

        if request.method not in ALLOWED_METHODS:
            audit("request.method_rejected", request.method, request_id=request.state.request_id)
            return reject(405, "Method not allowed", request)

        if suspicious_target(request):
            audit("request.suspicious_target", path[:200], request_id=request.state.request_id)
            return reject(400, "Invalid request target", request)

        oversized = _valid_body_limit(request)
        if oversized is not None:
            audit("request.body_rejected", path[:200], request_id=request.state.request_id)
            return reject(413, "Request body too large", request)

        if request.method == "POST" and not origin_allowed(request):
            audit("request.origin_rejected", request.headers.get("origin", "")[:200],
                  request_id=request.state.request_id)
            return reject(403, "Cross-origin request refused", request)

        ip = client_ip(request)
        supplied = request_token(request.headers)
        token_ok = verify_token(supplied)
        mfa_ok = True if not mfa_configured() else verify_totp(
            request.headers.get("x-agent-totp"))
        authenticated = token_ok and mfa_ok

        if api_path:
            retry = rate_limit_for_path(path, ip)
            if retry:
                audit("request.rate_limited", path[:200], actor=ip, request_id=request.state.request_id)
                return reject(429, "Too many requests; slow down", request, retry_after=retry)

            remaining = lockout_remaining(ip)
            if remaining and not authenticated:
                audit("auth.lockout_rejected", path[:200], actor=ip, request_id=request.state.request_id)
                return reject(429, "Too many failed sign-in attempts; retry later", request,
                              retry_after=remaining)

            if token_ok and not mfa_ok:
                audit("auth.mfa_failure", path[:200], actor=ip,
                      request_id=request.state.request_id)
                record_failure(ip)
                return reject(401, "Multi-factor code required or invalid", request)

        try:
            response = await call_next(request)
        except Exception:
            audit("request.error", path[:200], actor=ip, request_id=request.state.request_id)
            raise

        if api_path:
            if authenticated and response.status_code < 400:
                clear_failures(ip)
            elif response.status_code in (401, 403) and not authenticated:
                record_failure(ip)
        harden_headers(response, request)
        return response


def status(limit: int = 20) -> dict:
    """Safe, non-secret security posture for the authenticated UI."""
    recent = []
    try:
        with closing(_connect()) as con:
            rows = con.execute(
                "SELECT created_at,event,actor,detail,request_id FROM audit_log "
                "ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),)
            ).fetchall()
            recent = [dict(row) for row in rows]
            state = con.execute(
                "SELECT COUNT(*) AS locked FROM auth_state WHERE locked_until>?",
                (int(time.time()),),
            ).fetchone()
    except (sqlite3.Error, OSError):
        state = None
    return {
        "token_configured": token_configured(),
        "token_fingerprint": token_fingerprint(),
        "token_strength": token_strength(),
        "mfa_enabled": mfa_configured(),
        "mfa_algorithm": "TOTP RFC 6238 (SHA-1, 6 digits, 30s step, +/-1 step)",
        "mfa_header": "X-Agent-TOTP",
        "mfa_secret_configured": bool(totp_secret()),
        "max_auth_failures": max_failures(),
        "failure_window_seconds": failure_window(),
        "lockout_base_seconds": lockout_base(),
        "lockout_cap_seconds": lockout_cap(),
        "general_rate_limit_per_minute": general_rate_limit(),
        "max_body_bytes": max_body_bytes(),
        "locked_addresses": 0 if state is None else state["locked"],
        "headers": ["CSP", "HSTS (https)", "X-Frame-Options", "nosniff", "CORP", "COOP"],
        "recent_audit": recent,
    }
