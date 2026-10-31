# Launch readiness: desktop beta vs public service

The current app is an **experimental desktop beta**, not a verified production application for thousands of people.

## Implemented in repository
- Electron desktop setup, bundled Python backend, Rust gateway packaging and user-selected llama.cpp inference.
- SQLite project/task/artifact/event store with indexed queries, foreign keys and WAL.
- PostgreSQL reference schema in `database/postgres/001_multi_tenant.sql` with organizations, membership, projects, idempotent agent jobs, audit events and tenant row-level security.
- Cross-platform packaging CI and unit tests.

## Not implemented or not validated
- Automatic model download, verified hashes, license acceptance, model catalog, updates.
- Bundled llama.cpp executable, GPU driver installation or clean-machine compatibility testing.
- PostgreSQL backend wiring, hosted multi-tenant authentication, migrations, worker leases, autoscaling, billing or production monitoring.
- Code signing/notarization, automated security audit, end-to-end inference testing on real GPUs, high-concurrency load testing.

## Required gates before public launch
1. Obtain successful installer artifacts for Windows, macOS and Linux and test each on a clean VM/device.
2. Validate model download licensing/checksums, inference compatibility, prompt limits and resource exhaustion.
3. Harden loopback authentication and origin controls, process supervision, dynamic ports and update signatures.
4. Run authenticated multi-tenant PostgreSQL migrations and tenant-isolation tests; enforce RLS with non-owner app roles.
5. Test worker idempotency, lease recovery, retries, cancellation, auditability and disaster recovery.
6. Perform dependency scanning, security review, penetration tests, monitoring, SLOs and staged rollout.

Do not market as production-ready or claim capacity for thousands of concurrent users without these gates.
