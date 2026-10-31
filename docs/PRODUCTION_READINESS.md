# Production readiness and scale gates

**Current status: developer preview, not ready for thousands of users.**

## What works today
- Local FastAPI + browser Code Studio, manual approved file editing, and chat with a separately configured model.
- Experimental Electron packaging, Python backend bundling, Rust gateway, llama.cpp integration, SQLite local history.
- SQLite WAL/busy timeout and history index for local usage.

## Production database blueprint
The PostgreSQL migrations under `database/postgres` model organizations, users, memberships, projects, conversations, messages, durable jobs, approvals and audit events. The queue lease uses `FOR UPDATE SKIP LOCKED` to avoid competing workers claiming the same queued job. The schema is **not yet wired into the API**, and tenant isolation is not yet enforced in the running application. The SQL is a foundation, not a completed scalable service.

## Must-pass launch gates
1. Tenant-aware authentication (OIDC), membership authorization on every resource, and database row-level security or equivalent defense-in-depth.
2. Durable queue worker with idempotent retries, lease recovery, cancellation and per-tenant rate limits.
3. Dedicated isolated code execution workers; never mount privileged Docker sockets or run untrusted code on the API host.
4. Secure secret storage, encryption, log redaction, signed binaries, vulnerability scanning, and third-party security review.
5. Observability (traces, metrics, logs), backups with restore drills, schema migrations with rollback strategy, and disaster recovery.
6. Load tests for 100, 1,000 and 10,000 concurrent users with measured p95 latency, error rate, GPU throughput and cost.
7. Installer smoke tests on clean Windows/macOS/Linux machines, model download checksums, GPU detection and graceful fallback.
8. Capacity planning: local GPU inference is limited by each user's hardware; cloud orchestration and support services still need hosting for a multi-user SaaS.

Do not claim production readiness or user capacity without these tests.
