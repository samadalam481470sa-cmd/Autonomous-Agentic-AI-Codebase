# Threat model

## Assets

- Project source files and approved checkpoint history
- The local SQLite databases (messages, checkpoints, code index, semantic
  vectors, security audit)
- The administrator token and any model-provider API key
- The operator's machine, reachable through the optional Docker execution path
- Model outputs and retrieved repository excerpts used as prompt context

## Adversaries and inputs

Untrusted prompts, model outputs, tool arguments, workspace files, repository
excerpts, uploaded audio (local voice) and remote AgenticSeek responses can all be
adversarial. A hostile browser page could attempt cross-origin requests. An
attacker with network access to the API could guess the administrator token.

## Controls now implemented

- Digest-based, constant-time administrator authentication on every API route
  except `/health`; optional digest-only secret storage.
- Per-address failed-authentication ledger with exponential lockout, plus a
  correct-token bypass so lockouts cannot be used to deny the operator.
- Sliding-window rate limits, stricter for AI, chat, agent, execution and
  integration endpoints; `429` responses carry `Retry-After`.
- Method allowlisting, encoded-traversal and NUL rejection, method-override
  rejection, request-body ceiling and foreign-Origin rejection for writes.
- CSP, HSTS on HTTPS, nosniff, frame denial, referrer and permissions policies,
  CORP/COOP, `no-store` on API responses and no `Server` header.
- Append-only audit log of security events with a 2,000-entry cap, exposed only
  through an authenticated status endpoint. Tokens never appear in it.
- Workspace path containment, symlink refusal for edits, immutable `.agent`/`.git`
  metadata, diff-first writes with SHA-256 conflict checks and reversible
  checkpoints.
- Direct model file writes and host command execution are disabled by default.
  Optional execution is Docker-only, allowlisted, networkless, resource-capped
  and requires explicit approval headers.
- Retrieved repository text is labelled untrusted in prompts and never executed
  by the UI. Studio preview is a sandboxed iframe with scripts disabled.

## Defence-in-depth controls (new)

- Request-integrity checks reject duplicate framing headers, conflicting
  `Content-Length`/`Transfer-Encoding`, header injection, oversized headers and
  ambiguous chunked API writes (request smuggling).
- `Host` must be loopback or explicitly allowlisted, blocking DNS rebinding
  against a local service; `Sec-Fetch-Site: cross-site` writes are refused in
  addition to the `Origin` allowlist.
- Structured fields are screened for SQLi, XSS, command injection, traversal,
  SSTI, XXE, NoSQL/LDAP injection, unsafe deserialization, prototype pollution,
  CRLF injection and internal SSRF targets. Free-text code is not blocked.
- Outbound URLs pass a DNS-safe SSRF guard: HTTP(S) only, no credentials, and
  every resolved address must be public. Model and delegation endpoints remain
  loopback-only.
- A per-caller egress budget bounds bulk data theft over the API; oversized
  responses are audited.
- A global failure-rate cooldown throttles distributed credential stuffing and
  password spraying without locking out the real token holder.
- The audit log is an HMAC hash chain with a verification endpoint, so edits,
  deletions and reordering are detectable.
- Static mounts are checked at startup for databases, `.env` files and
  repository metadata.
- The repository audit script and CI gate check committed secrets, dangerous
  sinks, unpinned dependencies, mutable CI actions, exposed databases/keys and
  root container users.
- Compose runs read-only, non-root, with all capabilities dropped and bounded
  process/memory/CPU limits.

## Residual risk

- No multi-user identity, roles or tenant isolation; one token reaches everything.
- No TLS in-process; encryption and global rate limiting depend on a reverse
  proxy.
- Rate-limit state is per process and lost on restart; the lockout ledger is a
  local unencrypted SQLite file.
- Prompt injection can still influence model *output*. Every write requires human
  approval of an exact diff, which limits but does not eliminate that risk.
- Malicious local files and TOCTOU races against a privileged external process
  are not fully mitigated without per-job containers or VMs.
- Third-party models and the optional GPL AgenticSeek service are outside this
  repository's trust boundary.
- Signature screening is a high-precision backstop for structured fields, not a
  replacement for parameterized SQL and output escaping; free-text fields are
  intentionally not blocked. Egress accounting is `Content-Length`-based and
  per process.
- The audit chain is tamper-evident, not tamper-proof: whoever holds
  `SECURITY_AUDIT_KEY` (or the token digest when it is unset) can recompute it.
  Ship entries to external storage for immutability, and set the key explicitly
  before rotating the administrator token.
- The `Host` allowlist must be configured for any non-loopback deployment
  (`SECURITY_ALLOWED_HOSTS`); otherwise API requests correctly return `421`.
- No independent penetration test or fuzzing campaign has been completed, and no
  software can guarantee immunity to every attack.

## Deployment requirements

Never expose this service directly to the public internet. For any shared
deployment: terminate TLS at a reviewed proxy, keep the token in a secret store,
enable backups and full-disk encryption, restrict egress, run each task in an
isolated container or VM, add real user identity and per-tenant authorization,
enable audit shipping, and obtain a security review. See
[security hardening](../docs/SECURITY_HARDENING.md) and
[launch readiness](../docs/LAUNCH_READINESS.md).
