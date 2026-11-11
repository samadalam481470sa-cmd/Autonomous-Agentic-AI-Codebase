# Build framework compliance map

This maps *Aetherion OmniForge AI: Build Framework* (22 pages) to the repository.
It is deliberately conservative: a phase is "done" only when the behaviour is
implemented and covered by a check. The framework's own rule is that the product
must not be called enterprise-grade until Phase 6 passes.

## Framework decisions

| Decision | Status |
| --- | --- |
| Agent-first workspace with an editor beside it | Implemented as the React dashboard (`apps/dashboard`) |
| Local-first default, hosted mode as an add-on | Implemented: SQLite, loopback, no cloud dependency |
| Three autonomy levels (Ask, Worktree, Sandbox) | Partial: Ask and bounded planning exist; worktree isolation and sandbox levels are not enforced |
| Human approves merges | Implemented by design: agents never write or execute |
| Extend through MCP, skills and plugins | Not implemented |
| Benchmark of real tasks instead of "does anything" | Not implemented as a scored suite |
| Code-OSS as the default IDE | Partial: overlay and migration scripts exist; not the default packaged IDE |
| Rust gateway, Python orchestrator, React UI, Go control plane | React/Python/Rust present; Go hosted control plane not implemented |
| PostgreSQL, Redis, Kubernetes only in hosted mode | Reference schema and manifests only; not runtime dependencies |
| Evidence panel with preview and trace | Partial: run steps and outputs are visible; app preview is not |

## Seven-phase roadmap

| Phase | Framework exit gate | Status |
| --- | --- | --- |
| 1. Contracts and event log | Run/tool/event schemas in `packages/contracts`; every agent step saved to SQLite | **Partial**: durable run/step log exists; shared contract package does not |
| 2. Benchmark baseline | 30 real tasks with a recorded pass rate | **Not started** |
| 3. Code-OSS build | Clean-machine install test passes | **Partial**: workbench overlay and migration exist; clean-machine gate not met |
| 4. Real local model on GPU | One model runs on the GPU with proof saved | **Not verified here**: adapters and probes exist; this VM has no GPU |
| 5. Worktrees, diffs and sandboxing | Per-task worktree, policy gate, gVisor/Firecracker isolation | **Partial**: policy gate, allowlists and approvals exist; worktree-per-task and kernel isolation do not |
| 6. Connectors and model router | Connector hub, MCP client, token vault, router with fallback and budgets | **Partial**: local gateway, local-only switch and model recommendation; router, vault and connectors missing |
| 7. Hosted platform and scale | Tenants, auth, billing, PostgreSQL/Redis/Go services, million-line ladder | **Not implemented** |

## Implemented in this increment

- Local device runtime: CPU/RAM/GPU/VRAM/disk/battery inventory with loopback
  inference-backend discovery.
- Thermal governor with EWMA, slope, prediction, hysteresis, cooldown, battery
  floor, audit ledger and agent-run pause (`409` + `Retry-After`).
- OS keep-awake (caffeinate, systemd-inhibit, SetThreadExecutionState), TTL,
  dashboard toggle and automatic release at critical temperature.
- Downloadable bundle builder with SHA-256 manifest, launchers for Linux/macOS
  and Windows, and a release workflow.
- Device dashboard page; agent runs load `AETHERION.md` project rules.
- Tests for parsing, recommendation tiers, governor transitions, keep-awake,
  the authenticated device API, thermal gating and bundle contents.

## Still required before "enterprise-grade"

1. Define run/tool/event schemas in `packages/contracts` and generate types.
2. Add 30 benchmark tasks and publish the pass rate.
3. Finish the Code-OSS build and test it on a clean machine.
4. Save verified GPU inference proof from real hardware.
5. Add Git worktree per task, full multi-file apply/undo and a real sandbox.
6. Build the connector hub, token vault and model router with fallback/budgets.
7. Build the hosted control plane (tenants, quotas, PostgreSQL, Redis, Go) and
   the 10k → 1M line scale ladder.

Until those gates pass, the honest description remains **experimental,
local-first preview**.
