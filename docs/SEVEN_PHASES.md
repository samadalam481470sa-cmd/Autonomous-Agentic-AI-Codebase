# Seven-phase build status

This is a gated program, not a claim that every phase is finished. A phase is
only marked **passed** when its gate runs in CI or on a clean machine. This
document records what exists now so the README and GitHub description do not
overstate the product.

## Status table

| Phase | Scope | Status | Gate |
| --- | --- | --- | --- |
| 0 | Contracts, event log, benchmark, CI | **partial** | Contract check, event log and 30-task harness pass; recorded starter baseline is 0/30. No model/agent score yet |
| 1 | Code-OSS workbench, agent window, Tab completion, installers | **partial** | Chat, approved rewrites and the new Agent Runs webview exist; no Tab completion, signed installer or clean-machine run |
| 2 | Agent core: runs, worktrees, policy, streaming tools | **partial** | Evented orchestrator, policy gate, worktree manager, streaming read-only tools and a bounded lead executor tested; no parallel runs, GitHub PRs, preview or production merge automation |
| 3 | Tree-sitter, LSP, dependency graph, embeddings, sandbox | **not started** | Existing FTS5/hybrid retrieval only; no new sandbox runtime or retrieval-quality gate |
| 4 | Language packs and connectors | **not started** | Toolchain registry exists; no pack manifests, MCP client, token vault or connector health tests |
| 5 | Scale ladder, memory, skills, replay, learning | **not started** | Existing feedback/LoRA scripts only; no held-out tasks or promotion loop |
| 6 | Hosted platform | **not started** | PostgreSQL reference schema only; no auth, Go control plane, billing, tenancy runtime or security review |

## Phase 0 — implemented now

- `packages/contracts/schemas.json` defines Run, RunEvent, ToolCall, ModelCall,
  Approval, Artifact, Memory, Connector and EvalResult.
- `scripts/generate_contracts.py` emits TypeScript, Python, Rust and Go bindings;
  `--check` fails CI when a binding is stale.
- `services/api/events.py` is the append-only run event log. SQLite triggers
  reject UPDATE and DELETE, sequences are allocated per run under
  `BEGIN IMMEDIATE`, credential-shaped payload keys are redacted, and SSE frames
  carry a sequence id for resume.
- Event log tests cover ordering, replay contiguity, immutability, redaction and
  streaming.
- `evals/benchmark/tasks.json` contains 30 deterministic tasks and
  `scripts/run_benchmark.py` runs each in a disposable directory with a timeout.
  The committed `baseline.json` is a **starter baseline of 0/30**, not a model
  score; the Phase 0 benchmark gate therefore remains open.

## Phase 1 — what exists and what is missing

Existing first-party overlay in `code_oss_integration/extension`: local chat,
approved selection rewrite, SSE parser, Open VSX product configuration and a
pinned upstream workflow. A new **Agent Runs** webview lists runs, creates goals,
advances/cancels steps and renders the event log as evidence; it never receives
the admin token or a model key. Missing: Tab autocomplete, inline edit streaming,
a first-party terminal, signed installers and any clean-machine installer test.
Do not call this IDE complete.

## Phase 2 — implemented now

- `services/api/orchestrator.py` appends `run.created`, `step.started`,
  `step.completed`, `step.failed`, `run.completed` and `run.cancelled`.
- `services/api/policy.py` is the single tool gate. It combines role, autonomy
  (`ask`/`worktree`/`sandbox`) and target; unknown roles, tools and paths fail
  closed; writes need an allowed path; commands, dependencies, new network hosts
  and merges require approval; merges always require a human.
- `services/api/worktrees.py` creates a branch and worktree per run under a
  confined root, lists them and removes them. A worktree is file isolation, not
  a security boundary.
- `services/api/chat_stream.py` now streams text **and** executes bounded,
  read-only tool calls (`list_files`, `read_file`, `search_files`) in one run.
  Writes and host commands remain unavailable in this path.
- New endpoints: `GET /api/agents/runs/{id}/events` and
  `GET /api/agents/runs/{id}/stream` (SSE, `after` sequence resume).

The new `services/api/executor.py` is a bounded lead-agent loop: every run gets
a fresh worktree, every tool call goes through the policy gate and audit log, and
only worktree-local read/search/write tools are implemented. Commands, package
installs, network access and merges are refused. Missing: parallel runs,
cost/token budgets, GitHub branches/PRs/CI, a preview server, and a reviewer UI
that turns the worktree diff into an approved merge.

## Phase 3–6 — deliberately not started

The plan says not to start a phase before the previous gate passes. The next
concrete gates are:

1. Run the benchmark with a real model/agent and record its score; the starter
   baseline is already 0/30 (Phase 0).
2. Build and install the Code-OSS workbench on a clean machine and exercise the
   Agent Runs panel there (Phase 1).
3. Only then add Tree-sitter/LSP retrieval, per-task microVM or gVisor sandboxes,
   connectors, learning promotion and the hosted control plane.

## Repository wording

The GitHub repository description must be changed in GitHub's repository
settings; this workspace has no API credentials for that action. Until Phases 0
and 1 pass, the description should say **experimental developer preview**, not
"enterprise-grade". The README already uses that wording.
