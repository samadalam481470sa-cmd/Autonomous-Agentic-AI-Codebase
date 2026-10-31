# Large repository indexing (experimental)

The backend exposes two authenticated endpoints:

- POST /api/index/refresh with JSON {"project":"demo"} indexes up to 10,000 source files in a workspace. It uses SHA-256 content hashes to avoid reindexing unchanged files.
- POST /api/index/search with JSON {"project":"demo","query":"authentication middleware"} returns up to 30 ranked SQLite FTS5 text matches with source paths and line numbers.

Use the same Bearer administrator token as the Studio API. The index lives in each project's .agent/index.sqlite3. It is a local plaintext index, so do not share it or expose the API to untrusted networks.

Limitations: no file deletion cleanup, background jobs, resumable indexing, semantic embeddings, dependency graphs, language server protocol, benchmarked million-line performance, or autonomous changes. This component is a first step toward relevant-code retrieval; it is not a full Cursor replacement.

For million-line workspaces, the next engineering gates are file-watcher-driven updates, deletion tracking, syntax-aware symbols and dependency edges, hybrid retrieval, safe patch review, isolated test execution, evaluation benchmarks, and multi-OS smoke testing. The project does not currently train model weights on the GPU.
