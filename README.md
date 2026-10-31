# Autonomous Agentic AI Codebase

A self-hostable, original **agentic coding assistant** foundation. Inspired by the workflows of ChatGPT, Claude, and Cursor, but not affiliated with or a copy of their proprietary software.

## Working features
- Chat workspace with project selection and saved conversations
- OpenAI-compatible model gateway (works with compatible hosted or local endpoints)
- Multi-step tool-use loop with explicit tool schema and bounded iterations
- Read, list, write and search workspace files; command execution only with explicit opt-in
- Workspace path containment and human confirmation for shell commands
- SQLite persistence, FastAPI HTTP API, React-free standalone TypeScript-ready web shell
- Unit tests and GitHub CI

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

This repository contains original implementation code. Study external projects' architecture and APIs, but do not reproduce proprietary ChatGPT, Claude, Cursor, or Microsoft source or branding. Microsoft's [Agent Framework](https://github.com/microsoft/agent-framework) is MIT licensed; third-party dependencies require license review and preservation of notices. No third-party source is vendored here.

## Scope

This is an initial **working foundation**, not a million-line implementation or a feature-complete ChatGPT/Cursor replacement. A million lines of code is a possible long-term scale, not a measure of product quality. See docs/ROADMAP.md for phased milestones.

## Optional AgenticSeek integration

An opt-in, separate-process bridge is available. Review [integration and licensing guidance](docs/AGENTICSEEK_INTEGRATION.md), [uploaded archive security findings](security/UPLOAD_SCAN.md), and [open-source references](docs/OPEN_SOURCE_REFERENCES.md). The bridge does **not** execute or vendor the uploaded GPL-3.0 archive. To use it, independently run and secure AgenticSeek, configure `AGENTICSEEK_URL`, `AGENTICSEEK_API_TOKEN` and `AGENT_ADMIN_TOKEN`, then call `POST /api/integrations/agenticseek/query` with a bearer administrator token and `{ "project": "demo", "message": "..." }`. The same administrator token protects `POST /api/projects/plan` and `GET /api/projects/{project}/plan`.

**Not yet supported:** complete Cursor-style IDE, safe arbitrary code execution, live application preview, autonomous background execution, or verified malware-free third-party agents. Do not expose the local API to the public internet.

## Code Studio (new)

Set `AGENT_ADMIN_TOKEN` to a strong random secret in `.env` or your process environment. Start the app and visit **http://127.0.0.1:8000/studio**. Enter the admin token, select a project, refresh files, open or create a file, edit its contents, click **Review diff**, then **Approve & save**. HTML preview uses a sandboxed iframe with scripts disabled. The chat workspace also requires the same token.

**Security boundaries:** This is an authenticated local development console, not a multi-user IDE. The browser token is held in page memory. The model's existing file-writing tool is not subject to Studio's human-approval workflow; do not connect untrusted models or users. The HTML preview is not an OS-level sandbox. Arbitrary command execution remains disabled by default, and a hardened per-task container execution service is **not yet implemented**. GitHub integration, PR creation and resumable background jobs are also future work.

## Desktop IDE and controlled execution (new)

The Electron desktop client in [apps/desktop](apps/desktop) opens the local Code Studio and can be packaged for Windows, macOS, and Linux. See [desktop and execution setup](docs/DESKTOP_AND_EXECUTION.md). A minimal VS Code bridge lives in [apps/vscode-extension](apps/vscode-extension). The optional execution endpoint uses a locked-down Docker container with an explicit allowlist, a user approval header, no networking, and resource limits. It is disabled by default.

**Security change:** AI tool calls can no longer directly write project files or execute host commands. Human-approved edits remain available in Code Studio. This limits the current agent's autonomous coding ability until an approved patch-proposal workflow is added. Do not describe this as feature parity with Cursor, a standalone installer, or a production-secure autonomous agent. GitHub Actions includes a manual desktop packaging workflow; unsigned installers must be evaluated before distribution.

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
