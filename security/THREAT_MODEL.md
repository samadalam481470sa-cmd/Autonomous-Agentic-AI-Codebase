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
- No independent penetration test or fuzzing campaign has been completed.

## Deployment requirements

Never expose this service directly to the public internet. For any shared
deployment: terminate TLS at a reviewed proxy, keep the token in a secret store,
enable backups and full-disk encryption, restrict egress, run each task in an
isolated container or VM, add real user identity and per-tenant authorization,
enable audit shipping, and obtain a security review. See
[security hardening](../docs/SECURITY_HARDENING.md) and
[launch readiness](../docs/LAUNCH_READINESS.md).
