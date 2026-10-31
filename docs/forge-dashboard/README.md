# Forge Dashboard

Forge Dashboard is the control center and account dashboard for Forge, a local-first AI code editor in the style of Cursor. Everything runs on your own machine. Models run on your GPU. Data lives in SQLite on your disk. No cloud database or hosted backend is required.

The dashboard has two surfaces:

- The **control center** manages what is happening on this machine right now: agents, worktrees, models, GPU memory, the scheduler, the code index, context, rules, MCP servers, hooks, reviews, telemetry, and settings.
- The **account dashboard** manages people and policy: usage, plan and billing, members, the organization tree, admin policies, integrations, API keys, the audit log, paired devices and runners, and security checks.

The app is written in React 18 and TypeScript with Vite. It talks to the Forge sidecar, a Rust process that listens on `127.0.0.1:7420`. When the sidecar is not running, the dashboard switches to built-in fixture data, so every screen still works during development.

"Forge" is a placeholder name. Change it in one place with `VITE_APP_NAME` (see [Configuration](#configuration)).

---

## Contents

1. [Quick start](#quick-start)
2. [What is in the box](#what-is-in-the-box)
3. [Screens](#screens)
4. [Architecture](#architecture)
5. [Project layout](#project-layout)
6. [Configuration](#configuration)
7. [Data and the sidecar API](#data-and-the-sidecar-api)
8. [Mock mode](#mock-mode)
9. [Design system](#design-system)
10. [Charts](#charts)
11. [Accessibility](#accessibility)
12. [Performance](#performance)
13. [Security model](#security-model)
14. [Keyboard shortcuts](#keyboard-shortcuts)
15. [Scripts](#scripts)
16. [Testing](#testing)
17. [Moving into the Code-OSS fork](#moving-into-the-code-oss-fork)
18. [Extending the dashboard](#extending-the-dashboard)
19. [Troubleshooting](#troubleshooting)
20. [Limitations](#limitations)
21. [Roadmap](#roadmap)
22. [Further documentation](#further-documentation)

---

## Quick start

Requirements:

- Node.js 20 or newer (tested on Node 22)
- npm 10 or newer
- Optional: the Forge sidecar running on `127.0.0.1:7420`

Install and run:

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:5174`. The app opens on the control center overview.

If the sidecar is not running, a yellow banner says so and the sidebar shows a **Mock** badge. All data then comes from `src/api/mock.ts`.

To force fixture data even when the sidecar is up:

```bash
VITE_USE_MOCK=1 npm run dev
```

To build for production:

```bash
npm run build      # type-checks, then builds to dist/
npm run preview    # serves dist/ on 127.0.0.1
```

---

## What is in the box

| Area | Count |
| --- | --- |
| Screens | 28 (17 control center, 11 account) |
| Shared components | Card, Stat, Badge, StatusBadge, Toggle, Tabs, Segmented, Meter, Bar, Field, SettingRow, SearchInput, CopyButton, Kv, EmptyState, Skeleton, ErrorState, PageHead |
| Composite components | DataTable, Modal, Drawer, Confirm, Toast system, CommandPalette, DiffView, Shell |
| Charts | LineChart, BarChart, StackedColumns, Heatmap, Sparkline (hand-rolled SVG, no chart library) |
| API methods | 82 typed methods in `src/api/client.ts` |
| Domain types | 45 interfaces and 15 type aliases in `src/types/index.ts` |
| Runtime dependencies | 3 (`react`, `react-dom`, `react-router-dom`) |

There is no UI kit, icon font, or chart library. Icons are an original SVG set in `src/components/Icon.tsx`.

---

## Screens

### Control center

| Route | Screen | What it does |
| --- | --- | --- |
| `/app` | Overview | Agents waiting on you, live agent output, VRAM by model, GPU and CPU load, recent agents, index state, open findings, monthly totals |
| `/app/agents` | Agents | Every agent run. Table view with filters, search, bulk stop, and CSV export. Tiled view shows 2, 4, or 6 live agents at once. "New agent" modal picks repo, model, mode, placement, and run mode |
| `/app/agents/:id` | Agent detail | Approval banner, tool-call timeline, streaming output, message box with interrupt, multi-file diff with per-hunk keep and reject, task list, context breakdown, terminal log, checkpoints with restore, token meter, side chat |
| `/app/worktrees` | Worktrees | Git worktrees per agent: ahead and behind main, dirty files, conflicts, setup status, disk. Merge with squash, merge commit, or PR. Prune stale worktrees. Shows the setup script |
| `/app/projects` | Projects | Long-running goals. Kanban board with drag and drop that respects dependencies. Dependency graph view. Coordinator details and project notes |
| `/app/checkpoints` | Checkpoints | Snapshots taken before agent edits, with raw and compressed size and restore |
| `/app/models` | Models | Every local model with state, VRAM, speed, first-token time, and context. VRAM planner to test model combinations. Load, unload, pin. Tune drawer for GPU layers, KV cache precision, context size, and a benchmark. Pull model modal |
| `/app/hardware` | Hardware | GPU utilization, VRAM, temperature, power. RAM against budget. Per-thread CPU grid. Four time-series charts |
| `/app/scheduler` | GPU scheduler | Jobs on the GPU now, the priority queue, raise, lower, pause, and the priority policy |
| `/app/index` | Index & search | Indexed repos with progress, languages, ignore patterns, and errors. Search playground with hybrid, semantic, grep, and symbol modes. Docs sources for @Docs |
| `/app/context` | Context | Item-by-item view of what the model sees next, grouped by kind, with drop and summarize. Reference list of @-mentions |
| `/app/rules` | Rules & skills | Rules with type, globs, scope, token cost, and use count. A live "which rules apply to this path" tester. Rule editor drawer. Skills, slash commands, and memories with approve and delete |
| `/app/mcp` | MCP & plugins | MCP servers with transport, scope, sandbox flag, state, latency, and errors. Per-tool enable and approval. Add server modal with config preview. Installed plugins and marketplace |
| `/app/hooks` | Hooks | Hooks per event with matcher, timeout, runs, denies, and errors. A tester that runs a hook with your payload. Recent runs table |
| `/app/reviews` | Reviews | Findings from BugBot, security review, and editor review, with severity meter, filters, and a detail drawer that starts a fix agent. Rollout health. Code tours |
| `/app/telemetry` | Telemetry | Tab accept rate, partial accepts, reverts, agent success. Accept-rate line, latency histogram, activity heatmap, performance budgets |
| `/app/settings` | Settings | General, models, Tab, agents (run mode, sandbox, network allowlist, deny list), indexing, privacy, network. Save and discard with change tracking |

### Account dashboard

| Route | Screen | What it does |
| --- | --- | --- |
| `/web` | Overview | Tokens, local share, cloud spend, members, devices, tokens by day and feature, seats, security posture, recent activity |
| `/web/usage` | Usage | 7, 14, or 30 days. Group by feature, model, or local versus cloud. Stacked daily chart, breakdown table, cloud cost per day, top members |
| `/web/billing` | Plan & billing | Plan, seats, license key, offline grace period, invoices |
| `/web/members` | Members | People and service accounts. Filter by role, bulk role change, detail drawer, suspend and reactivate, invite modal with email validation |
| `/web/organization` | Organization | Organization, teams, and groups drawn as a tree, plus team cards with run mode locks and token caps |
| `/web/policies` | Policies | Admin policies by category with enforce toggles |
| `/web/integrations` | Integrations | GitHub, GitLab, Slack, Linear, Google Workspace, Cloudflare, Sentry, Supabase. Connect and disconnect |
| `/web/keys` | API keys | Personal, service-account, and bring-your-own-key provider keys. Create with scopes and expiry. The full key is shown once |
| `/web/audit` | Audit log | Filter by level and actor, search, export |
| `/web/devices` | Devices & runners | Main machine, runners, phones, tablets. Pairing modal with code and countdown. Unpair |
| `/web/security` | Security | Six posture checks, SSO and MFA, active sessions with "end session" |

A full walkthrough of every screen is in [docs/screens.md](docs/screens.md).

---

## Architecture

```
┌──────────────────────────── Forge Dashboard (this repo) ───────────────────────────┐
│                                                                                     │
│  Shell (sidebar, top bar, banner, command palette)                                  │
│    └─ Routes (lazy-loaded pages)                                                    │
│         └─ Pages ──► useResource(key, fetcher) ──► api.* (src/api/client.ts)        │
│                       │ cache, polling, optimistic mutate                           │
│                       └─► useLiveEvents() ──► WebSocket /ws/events                  │
│                                                                                     │
└───────────────┬─────────────────────────────────────────────────────┬───────────────┘
                │ HTTP JSON /api/v1/*                                  │ WebSocket
                ▼                                                      ▼
┌────────────────────────── Forge sidecar (Rust, 127.0.0.1:7420) ─────────────────────┐
│ axum API · model manager (llama.cpp / vLLM / MLX) · GPU scheduler · indexer         │
│ agent runner · worktrees · hooks · MCP client · SQLite (WAL) · OS keychain          │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

Key decisions:

1. **One data hook.** Every page reads data through `useResource`. It gives a shared cache keyed by string, stale-while-revalidate, optional polling, and `mutate` for optimistic updates. There is no global state library.
2. **One API module.** `src/api/client.ts` is the only place that knows URLs. Each method has a typed return and a fixture fallback.
3. **Fail open to fixtures.** A network error flips the client into mock mode. A real HTTP error (4xx or 5xx) is shown to the user as an error state, not hidden.
4. **Lazy routes.** Each screen is its own chunk. The main bundle holds the shell, router, and shared components.
5. **Plain CSS with tokens.** One global stylesheet and one token file. No CSS-in-JS runtime.

Read [docs/architecture.md](docs/architecture.md) for the full design.

---

## Project layout

```
forge-dashboard/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts            Dev server on 127.0.0.1:5174, proxies /api and /ws to the sidecar
├── .env.example
├── docs/                     Long-form documentation
└── src/
    ├── main.tsx              Entry, theme before first paint, router, toasts
    ├── App.tsx               Routes and error boundary
    ├── nav.ts                Sidebar groups for both surfaces
    ├── vite-env.d.ts
    ├── types/index.ts        Domain types shared with the sidecar
    ├── api/
    │   ├── client.ts         Typed API client with mock fallback, glob matcher
    │   ├── hooks.ts          useResource, useLiveEvents, useConnection, useLocalPref, invalidate
    │   ├── mock.ts           Fixture data (seeded, stable across reloads)
    │   └── rng.ts            Seeded random number generator
    ├── lib/format.ts         Number, byte, time, and date formatting; CSV export; helpers
    ├── styles/
    │   ├── tokens.css        Color, type, radius, and size tokens for dark and light
    │   └── global.css        Layout, components, charts, diff, kanban
    ├── components/
    │   ├── Shell.tsx         App frame and theme hook
    │   ├── ui.tsx            Small building blocks
    │   ├── Table.tsx         DataTable
    │   ├── Overlay.tsx       Modal, Drawer, Confirm, Toasts, useAction
    │   ├── CommandPalette.tsx
    │   ├── DiffView.tsx
    │   ├── charts.tsx
    │   └── Icon.tsx
    └── pages/
        ├── app/              17 control center screens
        └── web/              11 account screens
```

---

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `VITE_USE_MOCK` | `0` | `1` always uses fixture data and never calls the sidecar |
| `VITE_APP_NAME` | `Forge` | Product name in the sidebar and logo |
| `FORGE_SIDECAR_URL` | `http://127.0.0.1:7420` | Dev-server proxy target for `/api` and `/ws` (read by `vite.config.ts`) |

Copy `.env.example` to `.env.local` to set these.

The dev server binds to `127.0.0.1` on purpose. Do not change it to `0.0.0.0`. Remote devices reach the machine through the sidecar's paired, encrypted connection, not through the dev server.

---

## Data and the sidecar API

All requests go to `/api/v1`. Responses are JSON. Errors use this shape:

```json
{ "code": "not_found", "message": "Agent ag_123 not found" }
```

The client turns that into an `ApiError` with `status`, `code`, and `message`.

Main resource groups:

| Group | Examples |
| --- | --- |
| Agents | `GET /agents`, `GET /agents/:id`, `POST /agents`, `POST /agents/:id/stop`, `POST /agents/:id/approvals/:toolCallId`, `POST /agents/:id/changes/hunks`, `POST /agents/:id/messages`, `GET /agents/:id/context`, `POST /agents/:id/summarize` |
| Worktrees | `GET /worktrees`, `POST /worktrees/:id/merge`, `DELETE /worktrees/:id`, `POST /worktrees/prune` |
| Models | `GET /models`, `POST /models/:id/load`, `POST /models/:id/unload`, `PATCH /models/:id`, `POST /models/pull`, `POST /models/:id/bench` |
| Hardware | `GET /hardware`, `GET /hardware/history?minutes=60` |
| Scheduler | `GET /scheduler/jobs`, `PATCH /scheduler/jobs/:id`, `POST /scheduler/jobs/:id/pause` |
| Index | `GET /index/repos`, `POST /index/repos/:id/resync`, `DELETE /index/repos/:id`, `GET /index/docs`, `POST /index/docs`, `GET /index/search?q=&mode=` |
| Customization | `GET /rules`, `PUT /rules/:id`, `GET /rules/applicable?path=`, `GET /skills`, `GET /commands`, `GET /memories`, `GET /hooks`, `POST /hooks/:id/test` |
| MCP and plugins | `GET /mcp/servers`, `POST /mcp/servers`, `POST /mcp/servers/:id/reconnect`, `GET /plugins`, `POST /plugins/:id/install` |
| Quality | `GET /checkpoints`, `POST /checkpoints/:id/restore`, `GET /projects`, `GET /reviews/findings`, `POST /reviews/findings/:id/fix`, `GET /rollouts`, `GET /tours`, `GET /telemetry/*` |
| Settings | `GET /settings`, `PUT /settings` |
| Organization | `GET /org/members`, `POST /org/members`, `PATCH /org/members/:id`, `GET /org/teams`, `GET /org/usage`, `GET /org/plan`, `GET /org/invoices`, `GET /org/integrations`, `GET /org/keys`, `POST /org/keys`, `GET /org/audit`, `GET /org/policies`, `PUT /org/policies/:id`, `GET /org/security` |
| Devices | `GET /devices`, `POST /devices/pairing`, `DELETE /devices/:id` |

Live events arrive on `ws://127.0.0.1:7420/ws/events?agents=<ids>`:

```ts
type LiveEvent =
  | { type: "token"; agentId: string; text: string }
  | { type: "tool"; agentId: string; name: string; status: string }
  | { type: "status"; agentId: string; status: string }
  | { type: "metric"; name: string; value: number };
```

The full endpoint reference, with request and response bodies, is in [docs/api.md](docs/api.md). The data model is in [docs/data-model.md](docs/data-model.md).

---

## Mock mode

Mock mode exists so the UI can be built and tested before every sidecar endpoint is ready.

- It turns on when `VITE_USE_MOCK=1`, or when a request to the sidecar fails at the network level.
- It turns off again only on reload. This avoids flicker when the sidecar restarts.
- Fixture data is generated by a seeded random generator, so it is the same on every load.
- Writes in mock mode return success after a short delay. Pages update local state optimistically, so the change shows in the UI. Nothing is saved.
- Live events are simulated by a timer that streams words into agent output and sends speed metrics.

All fixture values are made up for UI development. They are not measurements of any real system.

---

## Design system

The look is dense and quiet, like an IDE panel. Dark is the default. Light is a separate, chosen theme, not an inverted copy.

Tokens live in `src/styles/tokens.css`:

| Group | Tokens |
| --- | --- |
| Surfaces | `--bg`, `--surface-1`, `--surface-2`, `--surface-3`, `--surface-hover`, `--surface-active` |
| Text | `--text-primary`, `--text-secondary`, `--text-muted` |
| Lines | `--border`, `--border-strong`, `--grid`, `--axis` |
| Accent | `--accent`, `--accent-ink`, `--accent-soft`, `--focus` |
| Series | `--series-1` to `--series-8` (categorical, fixed order) |
| Sequential | `--seq-100` to `--seq-700`, `--seq-empty` |
| Status | `--good`, `--warning`, `--serious`, `--critical` and soft variants |
| Diff | `--diff-add-bg`, `--diff-del-bg`, `--diff-add-ink`, `--diff-del-ink` |
| Type | `--font-sans` (system UI), `--font-mono` |
| Shape | `--radius-sm` 4px, `--radius` 6px, `--radius-lg` 10px |

Rules:

- Status colors only mean state. They never stand in for a data series.
- Every status badge pairs color with an icon and a word.
- Text never uses a series color. Series color only marks the mark.
- Tables use tabular numbers so columns line up.

The theme toggle is in the top bar. The choice is saved in `localStorage` under `forge:theme` and applied before first paint.

More detail: [docs/design-system.md](docs/design-system.md).

---

## Charts

All charts are hand-written SVG in `src/components/charts.tsx`.

| Chart | Used for |
| --- | --- |
| `LineChart` | Change over time: VRAM, RAM, utilization, tokens per second, accept rate. Crosshair tooltip, optional area fill for a single series, optional threshold line |
| `BarChart` | One measure across buckets: Tab latency histogram, cloud cost per day. Per-bar tooltip, optional highlight rule |
| `StackedColumns` | Parts of a daily total: tokens by feature or model. Tooltip lists each part and the total |
| `Heatmap` | Agent runs by weekday and hour, on a one-hue sequential ramp |
| `Sparkline` | Small trend under a stat tile. Decorative, no tooltip |

Every plotted chart:

- Has one y-axis. There are no dual-axis charts.
- Uses 2px lines, rounded bar ends anchored to the baseline, and a 2px gap between stacked parts.
- Shows a legend when there are two or more series.
- Has a hover tooltip.
- Has a **Table** button that swaps the chart for the same numbers in a table.
- Resizes with its container through `ResizeObserver`.

The categorical palette was validated for color-vision deficiency in both themes. More in [docs/charts.md](docs/charts.md).

---

## Accessibility

- All interactive controls are real buttons, links, inputs, or selects.
- Toggles are checkboxes with `role="switch"` and an `aria-label`.
- Tabs use `role="tablist"`, `role="tab"`, and `aria-selected`.
- Modals and drawers trap focus, close on Escape, and return focus to the trigger.
- Toasts use `role="status"` with `aria-live="polite"`.
- Charts have `role="img"` with a label, plus a table view.
- Sortable table headers set `aria-sort`.
- Focus rings use `:focus-visible` with a 2px outline.
- Status is never shown by color alone.

---

## Performance

| Item | Approach |
| --- | --- |
| Initial load | Shell and shared code in one chunk (about 81 KB gzip). Each screen loads on demand (2 to 5 KB gzip each) |
| Data | Cached per key. Polling pauses when the tab is hidden |
| Charts | SVG paths are memoized on series, size, and scale |
| Live output | Streaming text is capped (600 to 2,400 characters per view) so long runs do not grow the DOM |
| Tables | Paginated (25 rows by default) |
| Dependencies | Three runtime packages |

---

## Security model

- The dev server and preview server bind to `127.0.0.1` only.
- The dashboard never stores secrets. API keys show only a prefix. A new key is shown once and never again.
- Destructive actions (stop agent, remove worktree, delete index, revoke key, unpair device, suspend member, end session) go through a confirm dialog that says what will happen.
- The UI states what the sidecar enforces: loopback bind, OS keychain for secrets, sandbox for agent commands, deny list, model checksums, and signed releases. The dashboard displays these; the sidecar enforces them.
- Text from tools, MCP servers, and web pages is shown as data. The dashboard never runs it.

Read [docs/security.md](docs/security.md) for the threat model.

---

## Keyboard shortcuts

| Keys | Action |
| --- | --- |
| `Ctrl+K` or `Cmd+K` | Open the command palette |
| `↑` `↓` `Enter` | Move and choose in the palette |
| `Esc` | Close the palette, a modal, or a drawer |
| `Cmd+Enter` or `Ctrl+Enter` | Start the agent in the "New agent" modal |
| `Tab` / `Shift+Tab` | Move focus; stays inside open dialogs |

The palette lists every screen in both surfaces, plus actions: start a new agent, toggle the theme, pair a device, and prune stale worktrees. It uses fuzzy matching.

---

## Scripts

| Script | What it does |
| --- | --- |
| `npm run dev` | Dev server with hot reload on `127.0.0.1:5174` |
| `npm run typecheck` | `tsc --noEmit` with strict settings |
| `npm run build` | Type-check, then production build to `dist/` with source maps |
| `npm run preview` | Serve `dist/` locally |

---

## Testing

The current build is verified by:

1. `tsc --noEmit` in strict mode with `noUnusedLocals` and `noUnusedParameters`.
2. A production build.
3. A headless Chrome pass that opens all 28 routes in mock mode, records console errors, and takes full-page screenshots in dark and light themes.

The recommended test stack and a full plan (unit tests for formatters and the glob matcher, component tests for DataTable and DiffView, Playwright flows for approval, merge, and key creation, and visual regression) are in [docs/testing.md](docs/testing.md).

---

## Moving into the Code-OSS fork

The dashboard is built to move into the editor without a rewrite.

1. Copy `src/` into `src/vs/workbench/contrib/forge/dashboard/` in the fork, or into a built-in extension `extensions/forge-dashboard/`.
2. Host it in a webview panel for the full dashboard, and reuse single screens (Agents, Context, Models) as React islands in workbench views.
3. Replace the CSS tokens with the workbench theme variables (`--vscode-editor-background` and friends). The token file is the only place colors are defined, so this is a one-file change.
4. Replace `fetch` calls with the workbench's sidecar client service. Keep `client.ts` method names so pages do not change.
5. Keep this code inside the `contrib/forge` folder so original code stays separate from third-party editor code.

The step-by-step plan is in [docs/code-oss-integration.md](docs/code-oss-integration.md).

---

## Extending the dashboard

To add a screen:

1. Add the types to `src/types/index.ts`.
2. Add a method to `api` in `src/api/client.ts`, with a fixture fallback.
3. Add fixture data to `src/api/mock.ts`.
4. Create the page in `src/pages/app/` or `src/pages/web/`. Read data with `useResource`. Use `useAction` for writes so the user gets a toast.
5. Add a lazy route in `src/App.tsx`.
6. Add a nav item in `src/nav.ts`. It shows up in the sidebar and the command palette.

Templates and conventions are in [docs/contributing.md](docs/contributing.md).

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Yellow "sidecar is not reachable" banner | The sidecar is not running on `127.0.0.1:7420`, or `FORGE_SIDECAR_URL` points elsewhere. Start the sidecar and reload |
| Mock badge stays after starting the sidecar | Mock mode only resets on reload. Reload the page |
| A screen shows "Could not load this view" | The sidecar returned an HTTP error. The message comes from the sidecar's `message` field. Check the sidecar log |
| Live output does not move | The WebSocket at `/ws/events` failed. In dev, the Vite proxy forwards it; check the proxy target |
| Theme flashes on load | `localStorage` is blocked. The app falls back to dark |
| Charts look empty | The series has fewer than two points, or all values are zero |

More in [docs/troubleshooting.md](docs/troubleshooting.md).

---

## Limitations

These are stated plainly so nobody mistakes the dashboard for a finished product.

- The dashboard is the front end only. The sidecar endpoints it calls are specified here but implemented in the sidecar repo.
- Writes in mock mode are not saved anywhere.
- The VRAM planner's KV-cache figure is an estimate. The benchmark gives real numbers.
- The pairing grid in the "Pair device" modal is a visual stand-in. A real build should render a standard QR code from the pairing payload.
- There is no internationalization yet. All strings are English.
- Automated tests beyond type-checking, build, and the screenshot pass are planned, not written.

---

## Roadmap

1. Wire every screen to the real sidecar and remove mock fallbacks from production builds.
2. Add the test suite in [docs/testing.md](docs/testing.md).
3. Move into the Code-OSS fork as a webview and React islands.
4. Add a real QR code renderer for pairing.
5. Add saved views for tables (column choice, filters, sort).
6. Add notifications from the sidecar (agent done, approval needed) to the browser.
7. Add i18n.

---

## Further documentation

| Document | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Layers, data flow, caching, live events, error handling, routing |
| [docs/screens.md](docs/screens.md) | Every screen: purpose, data, actions, states, and edge cases |
| [docs/api.md](docs/api.md) | Every sidecar endpoint the dashboard calls, with request and response shapes |
| [docs/data-model.md](docs/data-model.md) | Every type, field by field, and the matching SQLite tables |
| [docs/design-system.md](docs/design-system.md) | Tokens, components, layout, theming |
| [docs/charts.md](docs/charts.md) | Chart rules, palette validation, anatomy, how to add a chart |
| [docs/security.md](docs/security.md) | Threat model and how the UI supports it |
| [docs/testing.md](docs/testing.md) | Test strategy and the full test plan |
| [docs/code-oss-integration.md](docs/code-oss-integration.md) | How to move the dashboard into the editor fork |
| [docs/contributing.md](docs/contributing.md) | Conventions, templates, and the review checklist |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Problems and fixes |

---

## Repository access

This repository is meant to be public to read and private to write. Keep the default branch protected. Only the owner and the AI coding tools the owner uses (Claude, ChatGPT, and similar) should have write access. Do not add outside collaborators with write permission.
