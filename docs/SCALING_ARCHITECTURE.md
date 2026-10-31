# Scaling architecture and launch gates

## Reality check
The current desktop backend and SQLite store are **single-user local services**, not a production service for thousands of concurrent users. Local inference consumes each user's hardware and is not a shared cloud model.

## Local database
`services/api/project_store.py` creates versioned project, task, artifact, and event tables, with foreign keys, uniqueness constraints, WAL and indexed lookups. It is a foundation for reliable desktop persistence, not a distributed database.

## Production architecture
- Separate identity and tenant management, with organization/project authorization and RBAC on **every** request.
- PostgreSQL with `tenant_id` on all tenant-owned tables, row-level security, managed backups, migration versioning, read replicas and connection pooling.
- Redis or durable queue for scheduled tasks with retries, idempotency keys, lease timeouts and dead-letter handling.
- Object storage for immutable artifacts and backups, with encryption, retention controls and checksum verification.
- Code index: incremental content hashing, language-aware parsing, vector embeddings and hybrid lexical/vector retrieval.
- Orchestration: bounded planner/executor/reviewer state machine, checkpoints, human-approved patches and audit trails.
- Isolated sandbox execution: per-job disposable VM/container, no default network, secret redaction, CPU/memory/time quotas.
- Observability: structured logs, traces, metrics, SLOs, alerting, error budgets, rate limiting and abuse prevention.
- Delivery: signed/notarized installers, auto-update integrity, clean-machine tests, GPU compatibility matrix, rollback strategy.
- Security: independent review, dependency/SBOM scans, threat modeling, penetration testing and incident response.

## Release criteria
Do not advertise production readiness until CI and real hardware smoke tests pass for Windows/macOS/Linux; installer signing and safe model onboarding are complete; model tool calls are reliable; security review is complete; and load tests establish target concurrency, recovery behavior and latency.
