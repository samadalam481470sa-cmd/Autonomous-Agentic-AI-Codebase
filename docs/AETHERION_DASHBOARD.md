# Aetherion OmniForge dashboard

The dashboard in `apps/dashboard` is an original React 18 + TypeScript control
surface served by the existing FastAPI process at `/dashboard`. It is inspired
by the density of modern AI code editors but uses original layout, icons, names,
copy and styling; it contains no third-party UI kit, icon font or copied design
assets.

## Build and run

```bash
cd apps/dashboard
npm ci
npm run build        # type-checks, then writes dist/
cd ../..
AGENT_ADMIN_TOKEN=... python -m uvicorn services.api.main:app --reload --no-server-header
```

Open `http://127.0.0.1:8000/dashboard` and enter the administrator token (plus a
TOTP code when the service has `AGENT_TOTP_SECRET` configured). The prebuilt
bundle is committed, so a fresh clone serves the dashboard without Node; rebuild
after changing `apps/dashboard/src`.

Development mode with hot reload:

```bash
cd apps/dashboard && npm run dev   # http://127.0.0.1:5175, proxies /api to :8000
```

The Docker image builds the dashboard in a Node stage and serves the same
bundle, so `docker compose up --build` includes it.

## Layout

| Region | Contents |
| --- | --- |
| Title bar | Brand, project switcher, command palette, index action, panel toggles, lock |
| Activity rail | Explorer, search, security, settings |
| Explorer | Filtered project file list, hybrid search results, indexing controls |
| Center | File tabs with a read-only line-numbered viewer, or Security/Settings pages |
| Assistant | Tabs for streaming chat, grounded codebase Q&A with 👍/👎 citations, and multi-agent runs |
| Status bar | Task state, project, file and vector counts, feedback totals, auth state |

Shortcuts: `Ctrl`/`Cmd`+`K` opens the command palette; `Esc` closes it; arrow
keys and `Enter` navigate. Chat sends on `Enter`, adds a newline on `Shift+Enter`.

## Data flow

- Authentication uses the existing bearer token (and optional `X-Agent-TOTP`).
  Credentials are kept in React state only; nothing is written to
  `localStorage` except the project name.
- Files come from `POST /api/studio/read` and `GET /api/studio/files/{project}`;
  the viewer is deliberately read-only, and edits still go through the audited
  Studio diff-and-approval flow.
- Chat streams from `POST /api/chat/stream` and falls back to `POST /api/chat`
  when local streaming is disabled.
- Code Q&A uses `POST /api/ai/ask`; citations expose redaction and injection
  flags, and votes call `POST /api/ai/feedback`.
- Multi-agent runs use `/api/agents/*` (see below).
- 401/403 responses immediately lock the workspace and clear the in-memory token.

## Multi-agent runs

`services/api/orchestrator.py` stores runs and steps in local SQLite
(`ORCHESTRATOR_DB_PATH`, default `database/agent_runs.sqlite3`). A run is an
ordered, bounded plan of specialist steps:

| Mode | Steps |
| --- | --- |
| `build` | architect → coder → tester → security → reviewer |
| `plan` | architect → reviewer |

Endpoints (all authenticated and rate limited to 30 requests/minute):

| Endpoint | Purpose |
| --- | --- |
| `GET /api/agents/roles` | Roles, default sequences and the step cap |
| `POST /api/agents/runs` | Create a bounded run |
| `GET /api/agents/runs?project=` | List runs |
| `GET /api/agents/runs/{id}` | Full run with steps |
| `POST /api/agents/runs/{id}/advance` | Execute the next step exactly once |
| `POST /api/agents/runs/{id}/cancel` | Cancel pending work |

Each step receives bounded, redacted repository context. Agents **never write
project files, never execute commands, and cannot spawn further work**; a
failure blocks the run and can be retried, and the operator advances every step.
`ORCHESTRATOR_MAX_STEPS` caps the sequence at 12.

## Docker and Kubernetes

`Dockerfile` builds the dashboard in a Node stage, installs the Python app, runs
as an unprivileged user and exposes a health check.
`deploy/k8s/platform.yaml` contains a namespace, PVC, secret reference,
Deployment with probes and hardened `securityContext`, Service, HPA and a
default-deny NetworkPolicy.

## Honest scope

- The dashboard is single-user, loopback-first management UI. Multi-user
  identity, role-based access and hosted tenancy are not implemented.
- PostgreSQL and Redis are **not** runtime dependencies. A PostgreSQL
  multi-tenant reference schema exists under `database/postgres`, but the
  service still uses local SQLite. No Redis adapter is implemented.
- There is no Go service in this repository; the local inference gateway is
  Rust, the API and orchestrator are Python.
- Agents are bounded planners/reviewers; they do not autonomously edit a
  repository. That is a deliberate safety boundary, not a missing button.
- The Kubernetes manifests are for the API only and have not been applied to a
  live cluster in CI.
- No browser automation test runs in CI; `npm run build` type-checks the UI and
  the API smoke tests cover the endpoints it calls.
