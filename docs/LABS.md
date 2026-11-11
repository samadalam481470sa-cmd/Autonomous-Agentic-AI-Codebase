# Labs: GitHub learning, autonomous runs and diagrams

Labs is the experimental surface for expanding the local workspace without a
cloud account. It is deliberately bounded; none of these controls turns the
agent into an unrestricted internet service.

## Public GitHub learning

Set `GITHUB_LEARNING=1` on the API process, then open **Labs → GitHub learning**
in the dashboard and enter `owner/repository` or a GitHub URL.

The importer:

- talks only to the fixed `api.github.com` and `codeload.github.com` hosts;
- downloads a public branch archive, with a 24 MB compressed limit, 64 MB
  expanded limit, 3,000-file limit and 1 MB per-file limit;
- rejects absolute paths, `..` traversal, symlinks, hardlinks and binary files;
- stores source and documentation suffixes, plus `LICENSE`/`NOTICE` files;
- records repository, branch, commit-shaped archive id and the GitHub-reported
  SPDX license;
- creates a separate project named `gh_<owner>_<repo>_<id>` and indexes it with
  the normal incremental FTS5 + local semantic pipeline.

It is **retrieval learning**, not model-weight training. The learned project is
available in the project picker and through **Labs → Search learned
repositories**. No project source, embeddings, prompts or model weights are
uploaded. A GitHub token is optional and is read only from the server-side
`GITHUB_TOKEN` environment variable for a higher API rate limit.

Configuration:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GITHUB_LEARNING` | `0` | Set to `1` to enable the importer |
| `GITHUB_DB_PATH` | `./database/github_sources.sqlite3` | Local source metadata database |
| `GITHUB_TOKEN` | empty | Optional server-side GitHub API token |

Endpoints, all requiring the administrator token:

- `POST /api/github/learn` — `{ "repo": "owner/name", "branch": "main" }`
- `GET /api/github/sources`
- `POST /api/github/search` — `{ "query": "...", "limit": 8 }`

Only import repositories whose license permits your use. The importer records
the detected license but does not make a legal determination.

## Bounded auto-run

In **Assistant → Agents**, create a run and choose **Auto-run**. It advances the
existing specialist sequence (architect → coder → tester → security → reviewer
for `build`) until the run completes, blocks, or reaches the eight-step cap.

Auto-run is still **model-only**: it never edits project files, runs a compiler,
or executes a host command. Code generation remains available through the
existing `polyglot.solve` path, which requires the host-toolchain opt-in and
normal approval/autonomy gates.

`POST /api/agents/runs/{run_id}/auto-advance` with
`{ "max_steps": 8, "queue": false }` is the API equivalent. Set
`"queue": true` to put the bounded loop in the durable worker queue. A queued
job runs only when the worker is enabled and its policy/thermal/power gates
allow it.

## Architecture diagrams

Open **Labs → Diagrams** and select **Generate diagram**. The server scans up to
800 supported source files, resolves in-project imports for Python,
JavaScript/TypeScript, Rust, Java and Kotlin, and returns:

- a standalone, escaped SVG (downloadable);
- Mermaid `flowchart LR` source (downloadable);
- node/edge metadata and scan counts.

Third-party imports are ignored and the graph is focused to the highest-degree
60 nodes by default. There is no Graphviz, browser renderer, external service or
model call involved, so the result is deterministic and works offline.

`POST /api/diagrams/architecture` accepts
`{ "project": "demo", "max_nodes": 60, "max_files": 800 }`.

## Limits

- This is not a claim that the model can “solve anything.” Model quality,
  context, available toolchains, disk and hardware still bound results.
- Imported code is untrusted data. It is labelled as untrusted when retrieved
  into a model prompt and is never automatically executed.
- Auto-run consumes model calls and is bounded by the thermal/power gates.
- Full file-writing autonomy, arbitrary package installation and remote MCP
  servers remain separate, approval-gated features—not part of this Labs view.
