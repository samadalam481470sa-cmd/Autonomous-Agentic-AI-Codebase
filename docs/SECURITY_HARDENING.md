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

## Defence-in-depth request hardening

`services/api/hardening.py` adds controls below authentication. They are
enabled by default; every setting is in [.env.example](../.env.example).

### Request integrity and DNS rebinding

- Duplicate `Content-Length`, `Transfer-Encoding`, `Host`, `Authorization`,
  `X-Agent-TOTP` and `X-Agent-Session` headers are rejected with `400`.
- `Content-Length` together with `Transfer-Encoding`, a non-`chunked` transfer
  coding, or a non-numeric length is rejected. Ambiguous framing is the
  precondition for HTTP request smuggling.
- CR/LF/NUL in header values, invalid header names, more than 100 headers and
  header blocks above 32 KiB are rejected.
- The `Host` header must be loopback, `testserver`, or an entry in
  `SECURITY_ALLOWED_HOSTS` (wildcards such as `*.example.com` are supported).
  This blocks DNS rebinding against a local service; a mismatch returns `421`.
  Set the hostname of your reverse proxy before exposing the app.
- API writes require `Content-Length`; chunked writes get `411`, so the body
  limit cannot be bypassed by omitting the length.
- API writes must use `application/json` (or `application/*+json`); anything
  else gets `415`.
- Browser writes carrying `Sec-Fetch-Site: cross-site` get `403`, in addition
  to the existing `Origin` allowlist. There are no cookie sessions, so CSRF has
  no ambient credential to abuse.

### Injection screening

Structured request fields are screened for high-confidence SQL injection, XSS,
command injection, path traversal, SSTI, XXE, NoSQL/LDAP injection, unsafe
deserialization, prototype pollution, CRLF injection and internal SSRF
targets. A `high` or `critical` match returns `400` and records
`request.injection_blocked` with the category and rule name only.

Free-text fields (`message`, `content`, `code`, `diff`, `html`, `prompt`,
`query`, ...) are deliberately **not** blocked: this is a coding assistant, so
those fields legitimately contain SQL and HTML. They are stored through bound
parameters and never rendered as markup. This avoids turning the detector into
a denial-of-service against normal editing while still protecting identifiers,
paths, filenames and URLs.

### SSRF guard

`hardening.url_problem()` validates outbound URLs: only HTTP(S), no embedded
credentials, no single-label or internal hostnames, and every address returned
by the resolver must be public. Loopback, link-local, private, reserved,
multicast and IPv4-mapped-IPv6 forms are rejected. Local model and AgenticSeek
endpoints remain loopback-only by their own configuration. Redirects are
disabled on every outbound client.

### Data-exfiltration budget

Every API response with a `Content-Length` is charged to the caller's
one-minute budget (`SECURITY_EGRESS_BYTES_PER_MINUTE`, 64 MiB by default).
Exceeding it returns `429` with `Retry-After`. Responses at or above
`SECURITY_LARGE_RESPONSE_BYTES` (4 MiB) are audited. This raises the cost of
bulk repository or database theft over the API; it does not inspect content.

### Distributed credential guessing

Per-address lockouts cannot see a botnet. Failures are also counted globally:
`SECURITY_GLOBAL_FAILURE_LIMIT` failures in 60 seconds trigger a
`SECURITY_GLOBAL_COOLDOWN_SECONDS` pause for unauthenticated API traffic.
Requests with a valid token still succeed and clear their own failure state, so
an attacker cannot deny service to the operator. `GET /api/security/status`
reports the remaining cooldown.

### Tamper-evident audit trail

Each audit row stores `prev_hash` and `entry_hash`, an HMAC-SHA-256 over the
previous hash and the row fields. Deleting, reordering or editing an entry is
detectable. The key comes from `SECURITY_AUDIT_KEY` when set, otherwise from the
administrator-token digest; set it explicitly so token rotation does not start
a new chain. The ledger keeps `SECURITY_AUDIT_MAX_ENTRIES` rows (20,000 by
default) and records a pruning anchor so the retained chain stays verifiable.

Verify it with `GET /api/security/audit/verify` (authenticated), which reports
`ok`, the number of entries checked and the first inconsistent row.

### Static exposure and repository audit

- At import, static mounts are checked for protected directories (`database`,
  `.git`, `.ssh`, ...), `.env` files and repository roots. A problem is written
  to the audit log as `startup.static_exposure`.
- `python scripts/security_audit.py --fail-on high` scans the repository for
  committed credentials, dangerous sinks (`shell=True`, `eval`, `exec`,
  `pickle`, unsafe YAML, disabled TLS verification), unpinned dependencies,
  missing lockfiles, mutable CI actions, exposed databases/keys,
  world-writable files and a root container user. CI runs it on every push.
- The optional command tool no longer uses a shell: shell metacharacters,
  absolute paths and `..` are rejected, `shlex` parses the argv list, and
  provider credentials are removed from the child environment.

### Container defaults

Compose now runs with a read-only root filesystem, `cap_drop: ALL`,
`no-new-privileges`, a 256-process limit, 1 GiB memory and one CPU. The database
and workspace volumes remain writable; execution containers are separate and
networkless. The image sets `PYTHONDONTWRITEBYTECODE=1` so a read-only root
works.

### Coverage matrix

[security/ATTACK_COVERAGE.md](../security/ATTACK_COVERAGE.md) and the
authenticated `GET /api/security/coverage` endpoint map all 50 attack classes to
the controls that exist and to honest statuses (`mitigated`, `partial`,
`delegated`, `not_applicable`). It is generated from
`services/api/hardening.py`; it is documentation of coverage, not a claim of
immunity.

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
- **Signature screening is not a WAF.** It is a high-precision backstop for
  structured fields, not a substitute for the bound parameters and output
  escaping already used. Free-text fields are intentionally not blocked.
- **The Host allowlist needs configuration.** Behind a proxy, set
  `SECURITY_ALLOWED_HOSTS`; otherwise API calls return `421`.
- **Egress accounting uses `Content-Length`.** Streaming or chunked responses
  are not charged to the budget, and the limiter is per process.
- **The audit chain is tamper-evident, not tamper-proof.** An attacker with the
  audit key (or the administrator token when `SECURITY_AUDIT_KEY` is unset) can
  recompute a consistent chain. Ship entries to external storage for real
  immutability.
- **No multi-user isolation or TLS.** The single administrator token still
  reaches every project; run behind a TLS reverse proxy with a secret store.
- No independent penetration test or fuzzing campaign has been performed. The
  automated tests cover the controls above, not every possible attack. No
  software can guarantee that it cannot be hacked.

## Verifying

```bash
AGENT_ADMIN_TOKEN=test-token SECURITY_DB_PATH=/tmp/sec.sqlite3 \
  python -m pytest -q tests/test_security.py tests/test_hardening.py tests/test_mfa.py
python scripts/security_audit.py --fail-on high
python scripts/check_oss_licenses.py
```

`tests/test_security.py` asserts digest comparison, hashed-secret support,
lockout escalation, correct-token bypass during lockout, security headers, CSP,
origin rejection, method and body limits, encoded-traversal rejection, 429
`Retry-After`, audit logging without secrets and protected status output.
`tests/test_hardening.py` covers smuggling framing, duplicate headers, CRLF
injection, the Host allowlist, content-type and Sec-Fetch enforcement, blocked
SQLi/traversal, allowed free-text code, the SSRF guard, audit-chain tampering,
the global cooldown, the egress budget, the 50-entry coverage matrix and static
mounts.

## New audit events

`request.integrity_rejected`, `request.host_rejected`,
`request.cross_site_rejected`, `request.framing_rejected`,
`request.content_type_rejected`, `request.injection_blocked`,
`request.suspicious_input`, `egress.limit_reached`, `egress.large_response`,
`auth.global_cooldown`, `auth.global_cooldown_rejected` and
`startup.static_exposure`.
