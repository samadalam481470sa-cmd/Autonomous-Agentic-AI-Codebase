# AI code proposals (experimental)

The `POST /api/agent/propose` endpoint asks the configured OpenAI-compatible local or remote model to generate a **complete replacement** for one selected workspace file. It returns the source text, a unified diff, an SHA-256 digest of the previous file, and a flag indicating that approval is required.

Example:
```bash
curl -s http://127.0.0.1:8000/api/agent/propose \
  -H "Authorization: Bearer $AGENT_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project":"demo","path":"src/main.py","instruction":"Add a unit-testable parser for the existing input format"}'
```

**Nothing is written by the proposal operation.** Review the returned `diff` and `content`, then use `POST /api/studio/apply` with the same `expected_sha256`, proposed content, and the separate `X-Confirm-Change: approve` header to apply a change. A stale file hash is rejected. Use `POST /api/execution/run` with explicit approval and enabled isolated execution to run allowlisted build/test commands.

Do not automatically apply model-generated patches or execute model-authored commands. This feature requires a configured model and does not guarantee correct code or test results. The model can propose one file at a time and has a bounded context; it is not an end-to-end autonomous software-development loop or proof of million-line scalability.
