# Security hardening

This document describes the controls in `services/api/security.py` and
`SecurityMiddleware`, what they actually defend against, and the residual risks.
The application is still a **local, single-operator developer tool**. These
controls make it materially harder to attack; they do not make it safe to expose
to the public internet.

## Authentication

- Every API route except `/health` requires `AGENT_ADMIN_TOKEN` through
  `Authorization: Bearer <token>` or `X-Agent-Token`.
- Tokens are compared as SHA-256 digests using `hmac.compare_digest`, so the
  comparison is constant-time and the plaintext secret is never stored in the
  process after reading the environment.
- `AGENT_ADMIN_TOKEN_SHA256` lets an operator keep only the digest on disk. The
  digest is validated as 64 lowercase hex characters.
- Failures return a generic message; the response never reveals whether the
  token is missing, malformed or wrong.
- Audit entries record an event type and detail, never the token. The status
  endpoint exposes only a 12-character fingerprint of the digest.
- The token is held in page memory by the browser UIs; it is not written to
  `localStorage`, cookies, logs or the audit table.
- `token_strength` reports `weak` for secrets shorter than 12 characters and
  records an audit event. Generate tokens with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## Brute-force defence

Failed authentication is counted per client address in
`database/security.sqlite3` (or `SECURITY_DB_PATH`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `SECURITY_MAX_AUTH_FAILURES` | 5 | Failures allowed inside the window |
| `SECURITY_AUTH_WINDOW_SECONDS` | 300 | Sliding failure window |
| `SECURITY_LOCKOUT_BASE_SECONDS` | 60 | First lockout duration |
| `SECURITY_LOCKOUT_MAX_SECONDS` | 900 | Ceiling for exponential growth |

Each repeat offence doubles the lockout up to the cap. While locked, requests
without a valid token receive `429` with `Retry-After`; **a request with the
correct token is still allowed and clears the failure state**. That asymmetry
throttles guessing without letting an attacker lock the real operator out.

The lockout ledger survives process restarts. A successful authenticated
request from the same address clears its failure count.

## Two-factor authentication (optional TOTP)

Set `AGENT_TOTP_SECRET` to a base32 secret to require a time-based one-time
password in addition to the administrator token. Generate one with:

```bash
python -c "import base64,os;print(base64.b32encode(os.urandom(20)).decode())"
```

- Algorithm: RFC 6238 TOTP, HMAC-SHA-1, 6 digits, 30-second step, accepted for
  one step either side of the current time. Implemented with the standard library
  (`hmac`, `hashlib`, `struct`, `base64`); no dependency is added.
- Clients send the code in `X-Agent-TOTP`. The TOTP input in Studio and the chat
  workspace is attached to every `/api` request automatically.
- A valid token without a valid code receives `401` and is counted as a failed
  authentication attempt, so guessing codes is throttled by the same lockout and
  rate limits as token guessing. A code is valid for its 30-second window and may
  be used more than once inside that window; forcing a fresh code per request
  would need short-lived session tokens, which are future work.
- An invalid or too-short base32 secret disables MFA instead of locking the
  operator out, and `GET /api/security/status` reports `mfa_enabled`.
- The secret is read from the environment, is never included in responses or the
  audit log, and is never written by the application.

## Rate limiting

A per-process sliding-window limiter applies to every `/api` request, with
stricter buckets for expensive families:

| Bucket | Default |
| --- | --- |
| All `/api` requests | 300/minute |
| `/api/ai` | 60/minute |
| `/api/chat` | 40/minute |
| `/api/agent` | 30/minute |
| `/api/execution` | 20/minute |
| `/api/integrations` | 20/minute |

Exceeding a limit returns `429` with `Retry-After`. Limiter state is in memory,
so each worker process enforces its own budget; run one worker for this local
app, or front it with a proxy that enforces global limits.

## HTTP hardening

- Allowed methods are `GET`, `HEAD`, `POST`, `OPTIONS`; anything else gets `405`.
- Encoded traversal (`..`, `%2e%2e`, double encoding) and NUL bytes are rejected
  before routing; `X-HTTP-Method-Override` is refused.
- Request bodies above `SECURITY_MAX_BODY_BYTES` (2 MiB) are rejected with `413`.
- `POST` requests carrying a foreign `Origin` are rejected with `403`. Same-origin
  and loopback origins are allowed; extra origins need
  `SECURITY_ALLOWED_ORIGINS`.
- Responses carry `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy`,
  `Cross-Origin-Resource-Policy`, `X-Permitted-Cross-Domain-Policies` and a
  per-request `X-Request-ID`.
- HTML responses get a Content-Security-Policy restricted to the app's own
  origin (plus `'unsafe-inline'`/`'unsafe-eval'`, required by the bundled editor
  and inline UI scripts, and `worker-src blob:` for Monaco workers), and
  `Cache-Control: no-store`.
- API responses are `no-store`. HSTS is added on HTTPS requests.
- The application removes the `Server` header in middleware, but uvicorn adds its own at the protocol layer; run uvicorn with `--no-server-header` (as shown in the README) to suppress it.

Existing protections remain in place: path containment, symlink refusal for
edits, human approval plus SHA-256 conflict checks for every write, checkpointed
restores, sandboxed HTML preview and locked-down Docker execution.

## Audit trail

`audit_log` records `auth.failure`, `auth.lockout`, `auth.weak_token`,
`auth.unconfigured`, `request.rate_limited`, `request.method_rejected`,
`request.suspicious_target`, `request.body_rejected`,
`request.origin_rejected`, `auth.lockout_rejected` and `request.error`. The
table is trimmed to the newest 2,000 entries. Inspect it in Studio through the
**Security** button or `GET /api/security/status`.

## Residual risks

These are real and must be addressed before any shared deployment:

- **No per-user accounts or multi-tenancy.** One token grants full access to
  every project on the machine. Use the PostgreSQL reference schema and add an
  identity provider first.
- **No TLS.** Loopback traffic is plaintext; a public deployment needs a
  reverse proxy with TLS, HSTS and client-IP forwarding
  (`SECURITY_TRUST_PROXY=1` only behind that proxy).
- **Single-process limits.** Rate limiting is per process and resets on restart;
  the lockout ledger is SQLite and assumes one trusted local filesystem.
- **Persistent lockout can be induced.** An attacker who can reach the API can
  force lockouts; correct-token requests still work, but unauthenticated traffic
  is throttled.
- **SQLite is unencrypted at rest**, including the audit log, checkpoints and
  code index. Use full-disk encryption.
- **Model endpoints are trusted.** A remote model provider receives prompts and
  retrieved excerpts; use `LOCAL_MODEL_ONLY=1` to keep inference loopback-only.
- **Docker containment is not a security boundary** against kernel or container
  escapes, and command execution over the host remains disabled by default.
- No independent penetration test has been performed. The automated tests cover
  the controls above, not every possible attack.

## Verifying

```bash
AGENT_ADMIN_TOKEN=test-token SECURITY_DB_PATH=/tmp/sec.sqlite3 python -m pytest -q tests/test_security.py
python scripts/check_oss_licenses.py
```

`tests/test_security.py` asserts digest comparison, hashed-secret support,
lockout escalation, correct-token bypass during lockout, security headers, CSP,
origin rejection, method and body limits, encoded-traversal rejection, 429
`Retry-After`, audit logging without secrets and protected status output.
