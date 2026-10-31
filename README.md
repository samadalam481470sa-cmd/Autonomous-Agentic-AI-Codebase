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
- Bounded multi-file coding trials, explicit Docker-based test approval and up to three offline retries
- Optional local microphone transcription with whisper.cpp, separately run AgenticSeek browsing adapter, and SQLite feedback evaluation
- Optional local CUDA LoRA training script with held-out regression gate and versioned adapter rollback (not automatic GGUF loading)
- Unit tests, local hardware tests, GitHub CI, and a million-line index benchmark

## Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
python -m uvicorn services.api.main:app --reload
```

Open http://127.0.0.1:8000. Set MODEL_API_KEY, MODEL_BASE_URL, MODEL_NAME for real LLM responses. For a local model, point MODEL_BASE_URL at its compatible API.

**Security:** Command execution is disabled unless ALLOW_COMMANDS=1. If enabled, commands are run on the host; **do not enable for untrusted users**. This prototype is not a secure execution sandbox. Production requires isolated per-task containers or VMs, egress restrictions, authentication, tenant isolation, approval workflows, rate limits, and security review.

## Project architecture

```text
apps/web/                Browser chat/agent interface
services/api/            FastAPI, model gateway, agent tools, storage
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

This repository contains original app implementation and a **separately attributed MIT-licensed Monaco Editor source snapshot** in `third_party/monaco-editor`. Monaco's original copyright, MIT license and third-party notices are preserved. The compiled editor is built locally from the corresponding pinned npm release. Do not represent vendored Monaco lines as originally authored app code. Microsoft's [Agent Framework](https://github.com/microsoft/agent-framework) is MIT licensed; third-party dependencies require license review and preservation of notices. See [upstream provenance and code size](docs/REPOSITORY_CODE_SIZE.md).

## Scope

This is an **experimental developer preview**, not a million-line first-party implementation or a feature-complete ChatGPT/Cursor replacement. A million lines of code is a possible long-term scale, not a measure of product quality. See docs/ROADMAP.md for phased milestones.

## Optional AgenticSeek integration

An opt-in, separate-process bridge is available. Review [integration and licensing guidance](docs/AGENTICSEEK_INTEGRATION.md), [uploaded archive security findings](security/UPLOAD_SCAN.md), and [open-source references](docs/OPEN_SOURCE_REFERENCES.md). The bridge does **not** execute or vendor the uploaded GPL-3.0 archive. To use it, independently run and secure AgenticSeek, configure `AGENTICSEEK_URL`, `AGENTICSEEK_API_TOKEN` and `AGENT_ADMIN_TOKEN`, then call `POST /api/integrations/agenticseek/query` with a bearer administrator token and `{ "project": "demo", "message": "..." }`. The same administrator token protects `POST /api/projects/plan` and `GET /api/projects/{project}/plan`.

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

The main browser chat has a **Stream local chat** checkbox. It calls the authenticated `POST /api/chat/stream` endpoint when `LOCAL_MODEL_ONLY=1`, which relays SSE token deltas through the loopback Rust gateway. Completed answers are saved with the user message as an atomic SQLite pair. Errors, interrupted streams and missing end markers are not saved as completed answers. Streaming chat intentionally disables model tool calls; keep the checkbox off for the existing agent/tool chat. No model weights, GPU drivers or inference engine are bundled.

## Approved-edit checkpoints and guarded restore

Studio saves record the previous UTF-8 file in the user's **local SQLite database** before replacing it. The Studio **Restore checkpoint** button restores the most recent version only with explicit approval and only if the file still matches the version that checkpoint created. Restoration creates its own inverse checkpoint, allowing the restoration to be undone. Newly created files can be removed by restoring their initial checkpoint; the inverse checkpoint can recreate them. Approved multi-file batch applies also record per-file snapshots.

Checkpoints are limited to small files (200 KB), are scoped by project and file, and are not a substitute for Git, backups, or a crash-consistent multi-file transaction. The lock protects writes within this single Python process; external programs and multiple server workers can still change files concurrently. The feature has automated conflict and authorization tests but is **not** a guarantee of production-grade recovery.

## Code-OSS workbench migration (in progress)

The [Code-OSS migration guide](docs/CODE_OSS_MIGRATION.md) now provides an exact upstream source pin, branded `product.json` overlay using Open VSX, and a first-party local-chat sidebar extension. This is the initial workbench migration path rather than a claim that the finished desktop app has switched from Monaco. Run `python scripts/code_oss_migrate.py --clone` to prepare a separate MIT-licensed source checkout for local development, then follow the upstream build instructions. The Python/Rust local model server remains separate and reusable.

**Current status:** The existing Monaco desktop installers are still the downloadable experimental builds. The Code-OSS source overlay and extension must pass dedicated source-build, extension-host, GPU inference and clean-install acceptance tests before becoming the default IDE.
