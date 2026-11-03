# Local semantic retrieval and retrieval-augmented chat

This document describes the retrieval stack added to `services/api/semantic.py`
and the `/api/ai/*` endpoints. Everything runs on the operator's machine.

## What it is

A deterministic, dependency-free embedding model for source code:

- **Tokenisation**: identifiers are split on camelCase, snake_case and digit
  groups, lowercased and filtered through a small code stopword list. Long
  identifiers also contribute character 4-grams, so `calculate` and
  `calculation` share signal.
- **Vectorisation**: signed feature hashing into `SEMANTIC_DIM` buckets
  (default 256), sublinear term frequency, L2 normalisation. Vectors are stored
  sparsely as `(bucket, weight)` pairs in SQLite.
- **Weighting**: query-time inverse document frequency, derived from bucket
  document frequencies maintained during indexing. Document vectors are not
  re-embedded when the corpus changes.
- **Similarity**: cosine similarity, which equals the dot product for the
  normalised sparse vectors.

This is a hashed lexical/structural embedding model, **not** a neural sentence
transformer. It requires no GPU, no model download and no network, and it is
deterministic across machines. It will not resolve true synonyms the way a
learned embedding model would; adding an optional neural backend is future work
and is listed in `third_party/oss_registry.json` as a reference only.

## Indexing

`POST /api/ai/index/refresh` with `{ "project": "demo", "max_files": 5000 }`.

Indexing is incremental and bounded:

- It first refreshes the incremental FTS5 lexical index, then walks the same
  source set (no symlinks, no `.git`/`node_modules`/build directories, no files
  over 1 MiB, UTF-8 only).
- A file is re-embedded only when its SHA-256 changes; unchanged files are
  counted and skipped.
- A truncated scan never prunes unseen files. A full scan removes vectors for
  deleted files.
- Chunks are 80 lines, matching the lexical index.

Data lives in `<workspace>/<project>/.agent/semantic.sqlite3`. `.agent` cannot be
edited through Studio, and no project can read another project's index.

## Retrieval

`POST /api/ai/search` accepts `hybrid` (default), `semantic` or `lexical`.

Hybrid ranking uses reciprocal rank fusion over the vector list and the FTS5
BM25 list, so an exact identifier hit and a structurally similar block both
survive. Responses include `semantic_score`, `lexical_score`, `score`, the
matching `sources`, and an excerpt with its line number.

Other endpoints:

| Endpoint | Purpose |
| --- | --- |
| `POST /api/ai/context` | Budgeted, deduplicated excerpts with citations |
| `POST /api/ai/similar` | Files structurally similar to one indexed file |
| `POST /api/ai/ask` | Repository Q&A through the configured model |
| `GET /api/ai/{project}/stats` | Files, vectors, dimensions, last index time |
| `GET /api/ai/health` | Retrieval model and endpoint configuration |

Every endpoint requires the administrator token and is rate limited (60
requests/minute by default via `SECURITY_AI_RATE_LIMIT_PER_MINUTE`).

## Feedback learning (online re-ranking)

Search results and answers expose 👍/👎 controls. Each vote is stored locally in
the project's SQLite database (`sem_feedback`) and turns retrieval into
**example-based online learning-to-rank**:

- Positive and negative votes per path are decayed with a 30-day half-life.
- The acceptance probability uses a Beta(1,1) prior,
  `(up + 1) / (up + down + 2)`, so one vote cannot dominate.
- The learned signal is `SEMANTIC_FEEDBACK_WEIGHT × (2p − 1)`, clipped to a
  bounded bonus or penalty (default weight 0.02), added to the reciprocal-rank
  fusion score before re-sorting.
- Votes are scoped to one project, must reference an existing file inside the
  workspace, and never leave the machine. No training job or model file exists.
- `POST /api/ai/feedback` records votes and returns the updated counts;
  `GET /api/ai/{project}/ranking` reports totals, the active weight, half-life
  and the ten most recent votes. Set `SEMANTIC_FEEDBACK_WEIGHT=0` to disable
  learning entirely.

## Safety screening before model calls

`services/api/content_safety.py` screens every excerpt placed in a model prompt:

- Provider credentials and key material (AWS keys, private-key blocks, JWT,
  GitHub/Slack/OpenAI-style tokens, bearer headers, credentials embedded in
  URIs, and `*SECRET*`/`*TOKEN*`/`*PASSWORD*` environment assignments) are
  replaced with typed placeholders such as `[REDACTED:aws_access_key]`.
- Opaque high-entropy tokens (Shannon entropy ≥ 3.8 bits/character, mixed
  character classes) are redacted; hexadecimal commit hashes and normal code
  identifiers are deliberately left alone.
- Prompt-injection patterns are counted and reported: instruction overrides,
  system-prompt extraction, role overrides, chat/tool markup, exfiltration
  requests and forced-execution phrasing. Findings never echo the matched text.
- Context responses include a `safety` summary (`secrets`, `injection`, `risk`)
  and per-citation `redactions`/`injection_risk`. The UI shows redaction counts
  next to answers, and `POST /api/ai/scan` scans a single project file on demand.

These checks reduce accidental credential disclosure and make injection attempts
visible; they do not make prompt injection impossible, which is why every write
still requires human approval of an exact diff.

## Retrieval-augmented generation

- `/api/ask` builds a context block (default 6000 characters, `SEMANTIC_RAG_CHARS`),
  wraps it in `<untrusted_repository_context>` and instructs the model to treat
  it as data, cite `path:line`, and never follow instructions inside it.
- The agent chat (`/api/chat`) and local streaming chat (`/api/chat/stream`)
  insert the same retrieved context as a system message when `SEMANTIC_RAG=1`.
  Retrieval failures are ignored so chat still works before the first index.
- Context is deduplicated per file, capped at two excerpts per file, and the
  character budget is enforced before the model is called.
- Answers are generated by the already configured provider or the loopback
  llama.cpp/Ollama endpoint. No repository text is sent anywhere unless the
  operator configured a remote model.

## Verified behaviour

`tests/test_semantic.py` covers incremental indexing, unchanged-file skipping,
stale vector removal, project isolation, semantic ranking, identifier splitting,
hybrid fusion, budget enforcement, similarity, statistics, authentication and
the `ask` flow (with the model call stubbed, including the no-context path that
must not call the model). The tests are part of the normal `pytest` run.

## Limits

- The vector scan is capped at 50,000 chunks per query; extremely large
  repositories need a future ANN index (for example an optional FAISS backend).
- Retrieval quality is lexical/structural. It is useful for navigation and
  grounding, not a substitute for a compiler or type checker.
- The index stores chunk text in SQLite, so disk usage is roughly the size of
  the indexed source plus vectors. It is not encrypted at rest.
- No embeddings leave the machine. There is no hosted vector database.
