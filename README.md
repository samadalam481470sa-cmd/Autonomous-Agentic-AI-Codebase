# Autonomous Agentic AI Codebase

A self-hostable **agentic coding assistant** with original application code and a separately licensed upstream editor component. Inspired by the workflows of ChatGPT, Claude, and Cursor, but not affiliated with or a copy of their proprietary software.

## Verified scale and current build status

- **324,257 licensed upstream Monaco Editor source lines** were committed from Microsoft Monaco v0.57.0 (MIT), verified by [the vendor workflow](https://github.com/samadalam481470sa-cmd/Autonomous-Agentic-AI-Codebase/actions/workflows/vendor-monaco.yml). These are not first-party authored lines. Run `python scripts/code_metrics.py` for separate line counts.
- **One-million-line SQLite FTS5 indexing test passed** on a generated 1,000-file sample. Measured initial index **4.406 seconds**, search **0.013 seconds**, unchanged reindex **0.052 seconds** on GitHub's Linux runner. This validates lexical indexing only, not autonomous full-repository comprehension. [Benchmark workflow](https://github.com/samadalam481470sa-cmd/Autonomous-Agentic-AI-Codebase/actions/workflows/million-line-benchmark.yml).
- Desktop setup now probes each installed local llama-server for actual available GPU backends; Auto selects `-ngl auto` when GPU devices are confirmed and otherwise uses CPU. If GPU startup fails, the app retries CPU. No cloud GPU is required; an appropriate backend, driver and licensed GGUF model are still prerequisites.
- Desktop installers are unsigned experimental artifacts; consult [GitHub Actions](https://github.com/samadalam481470sa-cmd/Autonomous-Agentic-AI-Codebase/actions) and [Releases](https://github.com/samadalam481470sa-cmd/Autonomous-Agentic-AI-Codebase/releases) for verified build states, and test on a clean machine before distributing.

## Working features
- Chat workspace with project selection and saved conversations
- OpenAI-compatible model gateway (works with compatible hosted or local endpoints)
- Multi-step tool-use loop with explicit tool schema and bounded iterations
- Read, list and search workspace files; AI edits are proposed as diffs and require approval before applying
- Workspace path containment and human confirmation for shell commands
- SQLite persistence, incremental FTS5 code index, FastAPI HTTP API, offline Monaco Editor integration
- Local code-aware embedding index with hybrid vector + FTS5 search, similar-file lookup and retrieval-augmented chat (no model download, no network, deterministic)
- Learned retrieval: local 👍/👎 feedback re-ranks hybrid results with decayed, smoothed acceptance (no training job or model download), plus a security scan that redacts credentials and flags prompt-injection attempts before any excerpt reaches a model
- Hardened API: digest-compared admin token, optional TOTP two-factor codes, brute-force lockouts with exponential backoff, per-address rate limits, CSP and security headers, origin checks, body caps and an audit log
- License-verified third-party registry with an automated permissive-license and notice check
- Bounded multi-file coding trials, explicit Docker-based test approval and up to three offline retries
- Optional local microphone transcription with whisper.cpp, separately run AgenticSeek browsing adapter, and SQLite feedback evaluation
- Optional local CUDA LoRA training script with held-out regression gate and versioned adapter rollback (not automatic GGUF loading)
- Polyglot toolchain registry for 64 language families with local detection, starter scaffolding, check/build/test/run planning and argv-only execution
- Autonomous generate → compile/test → retry loop that writes to a trial directory first, then applies checkpointed changes in any language whose toolchain is installed
- Durable always-on local worker with retryable SQLite jobs, a persisted stop switch, `always`/`ac_only`/`manual`/`off` policies, active hours and a GPU thermal guard; optional sign-in autostart
- Unit tests, local hardware tests, GitHub CI, and a million-line index benchmark

## Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
python -m uvicorn services.api.main:app --reload --no-server-header
```

Open http://127.0.0.1:8000. Set `AGENT_ADMIN_TOKEN` to a strong random secret (the UIs and every API route require it; see [.env.example](.env.example)). Set MODEL_API_KEY, MODEL_BASE_URL, MODEL_NAME for real LLM responses. For a local model, point MODEL_BASE_URL at its compatible API.

**Security:** Set `AGENT_ADMIN_TOKEN` (24+ random characters) before starting; every API route except `/health` requires it. Command execution remains disabled unless `ALLOW_COMMANDS=1`, and enabling it runs commands on the host — **do not enable for untrusted users**. Authentication, brute-force lockouts, rate limits, security headers, origin checks and an audit log are implemented, but this prototype still has **no multi-user accounts or TLS** and is **not a secure execution sandbox**. Do not expose it to the public internet; see [hardening](docs/SECURITY_HARDENING.md) and the [threat model](security/THREAT_MODEL.md). Production also requires per-task containers or VMs, egress restrictions, tenant isolation and security review.

## AI code intelligence and hardened API (new)

A local retrieval engine in [services/api/semantic.py](services/api/semantic.py) indexes the workspace incrementally. Embeddings are computed offline from code-aware tokens (camelCase/snake_case splitting, character 4-grams) with signed feature hashing and query-time IDF; there is **no model download, GPU requirement or network call**. Vectors are stored sparsely in SQLite next to the FTS5 index, and hybrid ranking fuses cosine similarity with BM25 by reciprocal rank.

- `POST /api/ai/index/refresh` — incremental embedding of changed files only
- `POST /api/ai/search` — hybrid, semantic or lexical search with excerpts and line numbers
- `POST /api/ai/context` — budgeted, deduplicated citations
- `POST /api/ai/similar` — structurally similar files
- `POST /api/ai/ask` — repository Q&A grounded in retrieved excerpts
- `GET /api/ai/{project}/stats`, `GET /api/ai/health`

Chat (`/api/chat`) and local streaming chat (`/api/chat/stream`) automatically inject budgeted retrieved context when `SEMANTIC_RAG=1`; excerpts are explicitly labelled untrusted. Studio and the browser chat now expose **Index project**, **Search** and **Ask codebase** controls, plus a **Security** posture view.

All API routes are protected by [services/api/security.py](services/api/security.py): constant-time digest comparison, optional digest-only token storage (`AGENT_ADMIN_TOKEN_SHA256`), a persistent per-address failure ledger with exponential lockouts (a correct token always bypasses the lockout), sliding-window rate limits with `Retry-After`, method/body/origin limits, encoded-traversal rejection, CSP and security headers, request IDs, and a capped audit log exposed only to authenticated callers. Configuration is documented in [.env.example](.env.example) and the controls in [security hardening](docs/SECURITY_HARDENING.md); retrieval internals are in [local semantic retrieval](docs/SEMANTIC_RETRIEVAL.md).

This is hardening for a local single-operator tool, not a production internet service. Multi-user identity, TLS termination, global rate limiting and independent penetration testing remain outstanding.

## Aetherion OmniForge dashboard and multi-agent runs (new)

An original React 18 + TypeScript dashboard is served at **http://127.0.0.1:8000/dashboard** (prebuilt bundle committed in `apps/dashboard/dist`; source in [apps/dashboard](apps/dashboard)). It has a dense editor-style layout: activity rail, project explorer, file tabs with a read-only code viewer, a right-hand assistant with streaming chat, grounded codebase Q&A with 👍/👎 citations, and a security page showing lockouts, limits and the audit trail. `Ctrl`/`Cmd`+`K` opens a command palette. See [the dashboard guide](docs/AETHERION_DASHBOARD.md).

The multi-agent backend in [services/api/orchestrator.py](services/api/orchestrator.py) stores durable runs in local SQLite. `build` runs architect → coder → tester → security → reviewer; `plan` runs architect → reviewer. Every step is operator-advanced, receives bounded and redacted repository context, is capped by `ORCHESTRATOR_MAX_STEPS`, and **never writes files or executes commands**. Endpoints live under `/api/agents`, require the administrator token and are rate limited.

Build the UI with `cd apps/dashboard && npm ci && npm run build`. The Dockerfile builds it in a Node stage; `deploy/k8s/platform.yaml` provides hardened blueprint manifests. PostgreSQL and Redis are not runtime dependencies in this build, and there is no Go service; the local inference gateway is Rust and the API is Python. These are documented as scope limits rather than hidden.

## Seven-phase program (in progress)

The product is being built as seven gated phases: contracts/events, the Code-OSS workbench, the agent core, context and sandboxing, language packs and connectors, scale/learning, then the hosted platform. Only Phase 0 and part of Phase 2 pass their current gates; this is **not** an enterprise-grade release, and the GitHub description should say experimental until the Phase 0/1 gates pass. See [seven-phase status](docs/SEVEN_PHASES.md) for exactly what exists and what does not.

Phase 0 added [shared contracts](packages/contracts/schemas.json) with generated TypeScript, Python, Rust and Go bindings, an append-only run event log with redaction and SSE resume, and a [30-task benchmark](evals/benchmark/README.md) whose committed starter baseline is 0/30. Phase 2 added a single [policy gate](services/api/policy.py), [git worktrees](services/api/worktrees.py), evented orchestrator steps, streaming chat that can call read-only tools, and a [bounded lead executor](services/api/executor.py). The Code-OSS overlay now includes an Agent Runs webview for creating, advancing and auditing runs.

## Run on your own computer (new)

Download the bundle from a tagged release or Actions artifact, verify its
SHA-256, then run `./run.sh` (Linux/macOS) or `run.bat` (Windows). The launcher
creates a local virtual environment, prints an administrator token, binds only
to `127.0.0.1`, and opens `/dashboard`.

```bash
git clone https://github.com/samadalam481470sa-cmd/Autonomous-Agentic-AI-Codebase.git
cd Autonomous-Agentic-AI-Codebase
./run.sh              # or: python aetherion.py
python aetherion.py --check   # hardware, thermal and backend report
```

The app runs on your CPU, GPU and RAM with SQLite. Docker, PostgreSQL, Redis and
Kubernetes are not required for local use. The **Device** page shows hardware,
temperatures, the thermal governor, local model backends and a keep-awake toggle.
Agent runs pause automatically when the device runs hot, and the launcher holds
the machine awake for long sessions with a TTL and automatic release.

Build the downloadable archive with `python scripts/package_local.py`. Full
details, model sizing, thresholds and troubleshooting: [docs/LOCAL_RUNTIME.md](docs/LOCAL_RUNTIME.md).
Framework status: [docs/FRAMEWORK_COMPLIANCE.md](docs/FRAMEWORK_COMPLIANCE.md).

## Project architecture

```text
apps/web/                Browser chat/agent interface (classic)
apps/dashboard/          Aetherion OmniForge React + TypeScript control surface
services/api/            FastAPI, model gateway, agent tools, orchestrator, storage
deploy/                  Kubernetes blueprint manifests
services/worker/         Reserved for durable background execution
services/runtime-rust/   Reserved for hardened execution engine
packages/contracts/      Shared tool and API contracts
database/                Local SQLite (dev only)
infrastructure/          Docker deployment
security/                Security policy and risk register
tests/                   Automated tests
docs/                    Architecture and roadmap
.github/workflows/       CI
```

## Open source and legal provenance

This repository contains original app implementation and a **separately attributed MIT-licensed Monaco Editor source snapshot** in `third_party/monaco-editor`. Monaco's original copyright, MIT license and third-party notices are preserved. Every vendored, linked and referenced project is registered with its SPDX license, pin and notice path in [third_party/oss_registry.json](third_party/oss_registry.json); `python scripts/check_oss_licenses.py` fails the build if a bundled component is not permissively licensed or a notice is missing. The policy and attribution table are in [legal open source](docs/LEGAL_OPEN_SOURCE.md). The compiled editor is built locally from the corresponding pinned npm release. Do not represent vendored Monaco lines as originally authored app code. Microsoft's [Agent Framework](https://github.com/microsoft/agent-framework) is MIT licensed; third-party dependencies require license review and preservation of notices. See [upstream provenance and code size](docs/REPOSITORY_CODE_SIZE.md).

## Scope

This is an **experimental developer preview**, not a million-line first-party implementation or a feature-complete ChatGPT/Cursor replacement. A million lines of code is a possible long-term scale, not a measure of product quality. See docs/ROADMAP.md for phased milestones.

## Optional AgenticSeek integration

An opt-in, separate-process bridge is available. A pinned upstream AgenticSeek **GPL-3.0 git submodule** is now linked at `upstream/agenticseek` for optional independent source review; it is not bundled, installed, executed or included in the Code-OSS release. The [user-provided Forge Dashboard design specification](docs/forge-dashboard/README.md) is preserved as documentation only; the React dashboard source and Rust sidecar described there were not included in the upload. Review [integration and licensing guidance](docs/AGENTICSEEK_INTEGRATION.md), [uploaded archive security findings](security/UPLOAD_SCAN.md), and [open-source references](docs/OPEN_SOURCE_REFERENCES.md). The bridge does **not** execute or vendor the uploaded GPL-3.0 archive. To use it, independently run and secure AgenticSeek, configure `AGENTICSEEK_URL`, `AGENTICSEEK_API_TOKEN` and `AGENT_ADMIN_TOKEN`, then call `POST /api/integrations/agenticseek/query` with a bearer administrator token and `{ "project": "demo", "message": "..." }`. The same administrator token protects `POST /api/projects/plan` and `GET /api/projects/{project}/plan`.

**Not yet supported:** complete Cursor-style IDE, safe arbitrary code execution, live application preview, autonomous background execution, or verified malware-free third-party agents. Do not expose the local API to the public internet.

## Code Studio (new)

Set `AGENT_ADMIN_TOKEN` to a strong random secret in `.env` or your process environment. Start the app and visit **http://127.0.0.1:8000/studio**. Enter the admin token, select a project, refresh files, open or create a file, edit its contents, click **Review diff**, then **Approve & save**. HTML preview uses a sandboxed iframe with scripts disabled. The chat workspace also requires the same token.

**Security boundaries:** This is an authenticated local development console, not a multi-user IDE. The browser token is held in page memory. Direct model file-writing tools are disabled; Studio and batch proposals require explicit approval. Do not connect untrusted models or users. The HTML preview is not an OS-level sandbox. Allowlisted Docker execution requires an explicit approval header and remains disabled by default. Docker containment is not a complete security boundary against container escapes. GitHub integration, PR creation and resumable background jobs are also future work.

## Desktop IDE and controlled execution (new)

The Electron desktop client in [apps/desktop](apps/desktop) opens the local Code Studio and can be packaged for Windows, macOS, and Linux. See [desktop and execution setup](docs/DESKTOP_AND_EXECUTION.md). A minimal VS Code bridge lives in [apps/vscode-extension](apps/vscode-extension). The optional execution endpoint uses a locked-down Docker container with an explicit allowlist, a user approval header, no networking, and resource limits. It is disabled by default.

**Security change:** AI tool calls can no longer directly write project files or execute host commands. Human-approved edits, one-file/multi-file proposals, and bounded local test-retry workflows are available in Code Studio. Do not describe this as feature parity with Cursor, a standalone installer, or a production-secure autonomous agent. GitHub Actions includes a manual desktop packaging workflow; unsigned installers must be evaluated before distribution.

## Local GPU inference and multi-language database development

Run compatible open-weight models locally using an OpenAI-compatible loopback endpoint, such as Ollama. Set `LOCAL_MODEL_ONLY=1`, `LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1`, and `LOCAL_MODEL_NAME=qwen2.5-coder:7b`. When local-only mode is enabled, the agent uses the loopback endpoint instead of a remote inference API. GPU use depends on compatible hardware and installed model runtime; see [setup and limitations](docs/LOCAL_GPU_AND_LANGUAGES.md).

The [language catalog](services/api/languages.py) recognizes dozens of programming languages and file types; arbitrary UTF-8 source files can be edited. PostgreSQL and SQLite starter migrations are in [database/templates](database/templates). **This does not imply every language can be compiled, debugged or executed**, or that the app can provision arbitrary databases yet. Local inference avoids metered remote API usage but does not remove finite model context, VRAM or processing limits.

## Polyglot autonomous coding and always-on local worker (new)

The agent can work in any language the owner's machine can actually build. [services/api/toolchains.py](services/api/toolchains.py) declares probes, check/build/test/run commands, starter files and install hints for 64 language families (Python, JS/TS, Rust, Go, Java, Kotlin, C/C++, C#, Swift, Dart, Ruby, PHP, Elixir, Haskell, Zig, COBOL, Fortran, Solidity, Verilog and more). Commands are argv lists executed **without a shell**, so file names and model output cannot inject commands. Missing toolchains are reported with an install hint instead of being faked. Unknown languages can be added at runtime with `POST /api/polyglot/register` and are persisted locally.

`POST /api/polyglot/scaffold` writes a runnable starter project and verifies it with the real toolchain. `POST /api/polyglot/solve` runs a bounded generate → compile/test → retry loop in a disposable trial directory and applies the result only with approval or `AGENT_AUTONOMY=1` (the desktop default); applied files get normal checkpoints. [services/api/worker.py](services/api/worker.py) provides a SQLite-backed always-on queue that runs while the computer is on, prefers the local model and GPU, and stops with the machine, the persisted Stop control, or the `off` policy. Power, active-hours and GPU-temperature limits are available. A browser control page is at **http://127.0.0.1:8000/control**. See [polyglot and always-on](docs/POLYGLOT_ALWAYS_ON.md) for endpoints, autostart and limits. Host toolchain execution stays opt-in (`AGENT_HOST_TOOLCHAIN=1`), no model, compiler, driver or GPU is bundled, and no certified GPU-inference or clean-machine test is claimed.

## Rust + llama.cpp inference pipeline

The new Rust gateway in [services/runtime-rust](services/runtime-rust) supports `agentic-runtime serve` alongside the workspace scanner. It forwards bounded OpenAI-compatible requests to a **locally running llama.cpp server**. Python agent orchestration can use it through `LOCAL_MODEL_ONLY=1` and `LOCAL_MODEL_BASE_URL=http://127.0.0.1:8088/v1`. The local gateway enforces a concurrent-request limit, output token cap and request-size limit. Python additionally trims earlier conversation history using a character budget.

See [complete local inference setup](docs/RUST_LLAMA_INTEGRATION.md) for GGUF Q4 quantization, GPU offload and exact startup commands. llama.cpp itself (C/C++) executes the model; Rust is the efficient gateway/indexing layer. **No claim of zero GPU usage, unlimited context, automatic model downloads or validated hardware compatibility is made.**

## Experimental downloadable desktop beta (2026)

The [desktop packaging workflow](.github/workflows/desktop.yml) now builds a bundled Python backend and Rust inference gateway on Windows, macOS and Linux. The Electron app starts the local Python service, displays a hardware/setup screen, lets users select a llama.cpp executable and GGUF model, and can launch both the model and Rust gateway locally. The onboarding screen also supports user-initiated Hugging Face HTTPS model downloads with a **required user-supplied SHA256 checksum and explicit license confirmation**. Model downloads are capped at 20 GB. See [local onboarding](docs/LOCAL_ONBOARDING.md).

The app **does not bundle llama.cpp or GPU drivers**. A downloaded GGUF alone cannot run without a compatible llama.cpp binary. Installer builds, real GPU inference and clean-machine startup have not yet been verified. This is not a production release for thousands of users.

The local SQLite [project store](services/api/project_store.py) uses indexed transactional project/task/artifact/event tables. A separate [PostgreSQL multi-tenant reference schema](database/postgres/001_multi_tenant.sql) and [launch gates](docs/LAUNCH_READINESS.md) document the architecture required before any hosted multi-user launch; the hosted PostgreSQL service is **not implemented**.

## Local inference runtime verification

Desktop setup uses a supervised loopback-only llama.cpp process with serialized startup, GPU-to-CPU fallback in Auto mode, explicit manual-offload behavior, and local gateway reachability checks. GPU detection alone is not called GPU acceleration: the setup only confirms offload when llama.cpp emits recognizable nonzero GPU-layer evidence. These tests exercise the startup control path; no real NVIDIA, AMD or Apple GPU inference run is certified yet. See [GPU setup](docs/GPU_SETUP_GUIDE.md) and [the desktop CI](.github/workflows/desktop.yml).

The proposed Code-OSS-based editor, streaming model router, worktree sandbox and 300k+ first-party LOC roadmap are future architecture goals, not implemented features of this Monaco-based desktop build.

### Opt-in local streaming chat

The main browser chat has a **Stream local chat** checkbox. It calls the authenticated `POST /api/chat/stream` endpoint when `LOCAL_MODEL_ONLY=1`, which relays SSE token deltas through the loopback Rust gateway. Completed answers are saved with the user message as an atomic SQLite pair. Errors, interrupted streams and missing end markers are not saved as completed answers. Streaming chat can execute only read-only tools inside the same run; writes and host commands remain disabled. No model weights, GPU drivers or inference engine are bundled.

## Approved-edit checkpoints and guarded restore

Studio saves record the previous UTF-8 file in the user's **local SQLite database** before replacing it. The Studio **Restore checkpoint** button restores the most recent version only with explicit approval and only if the file still matches the version that checkpoint created. Restoration creates its own inverse checkpoint, allowing the restoration to be undone. Newly created files can be removed by restoring their initial checkpoint; the inverse checkpoint can recreate them. Approved multi-file batch applies also record per-file snapshots.

Checkpoints are limited to small files (200 KB), are scoped by project and file, and are not a substitute for Git, backups, or a crash-consistent multi-file transaction. The lock protects writes within this single Python process; external programs and multiple server workers can still change files concurrently. The feature has automated conflict and authorization tests but is **not** a guarantee of production-grade recovery.

## Code-OSS workbench migration (in progress)

The [Code-OSS migration guide](docs/CODE_OSS_MIGRATION.md) now provides an exact upstream source pin, branded `product.json` overlay using Open VSX, and a first-party local-chat sidebar extension. This is the initial workbench migration path rather than a claim that the finished desktop app has switched from Monaco. Run `git submodule update --init upstream/code-oss` followed by `python scripts/code_oss_migrate.py` to apply the first-party overlay to the pinned upstream workbench source, then follow the upstream build instructions. The submodule links to MIT-licensed upstream source and is not a GitHub fork. The Python/Rust local model server remains separate and reusable.

**Current status:** The existing Monaco desktop installers are still the downloadable experimental builds. The Code-OSS source overlay and extension must pass dedicated source-build, extension-host, GPU inference and clean-install acceptance tests before becoming the default IDE.
