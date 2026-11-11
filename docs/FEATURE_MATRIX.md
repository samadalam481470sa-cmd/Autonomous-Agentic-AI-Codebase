# Feature coverage

This is the audit map for implemented capabilities. “API” means the authenticated FastAPI surface, which is browsable at `/docs`; it does not mean a cloud service.

| Capability | User-facing surface | Backend | Automated coverage |
| --- | --- | --- | --- |
| Chat, project selection, saved history | Chat `/` | `/api/chat`, `/api/projects/{project}/history` | `tests/test_engine.py`, `tests/test_ui_web.py` |
| Project registry | Chat **New project** | `POST /api/projects` | `tests/test_project_store.py` |
| Bounded project plan | Chat **Plan project** | `POST /api/projects/plan` | `tests/test_ui_web.py` |
| Streaming local chat | Chat **Stream local chat** | `/api/chat/stream` | `tests/test_chat_stream.py` |
| Local voice transcription | Chat **Local voice** | `/api/voice/transcribe` | `tests/test_voice.py` |
| AgenticSeek delegation | Chat **Browse with AgenticSeek** | `/api/integrations/agenticseek/query` | `tests/test_agenticseek.py` |
| Manual and AI single-file proposals | Studio **AI propose**, **Review diff**, **Approve & save** | `/api/agent/propose`, `/api/studio/*` | `tests/test_code_agent.py`, `tests/test_studio.py` |
| Multi-file proposals | Studio **AI multi-file**, **Approve batch** | `/api/agent/batch/*` | `tests/test_multi_file_agent.py` |
| Bounded test-and-retry trial | Studio **AI test & retry** | `/api/agent/trial/run` | `tests/test_repair_trial.py` |
| Approved Docker execution | Studio **Run tests** | `/api/execution/run` | `tests/test_execution.py` |
| Checkpoints and guarded restore | Studio **Restore checkpoint** | `/api/studio/checkpoints`, `/api/studio/restore` | `tests/test_checkpoints.py` |
| Indexed code search | Studio search and **Reindex** | `/api/index/*` | `tests/test_code_index.py`, `tests/test_ui_web.py` |
| Local learning status | Studio **Local learning → Status** | `/api/learning/{project}/status` | `tests/test_learning.py` |
| Opt-in feedback capture | Studio **Local learning → Save feedback** | `/api/learning/feedback` | `tests/test_learning.py` |
| Evaluation recording | Studio **Local learning → Record eval** | `/api/learning/evaluation` | `tests/test_learning.py` |
| HTML preview | Studio **HTML preview** | `/api/studio/preview` | `tests/test_studio.py`, `tests/test_ui_web.py` |
| Languages and local model config | API `/docs` | `/api/languages`, `/api/local-model/config` | `tests/test_languages_local.py` |
| Editor selection rewrite | VS Code bridge | `/api/ide/rewrite` | `tests/test_ide_rewrite.py` |
| Desktop setup, model download and runtime | Electron setup window | Desktop main/preload IPC | `apps/desktop/*.test.cjs` |
| LoRA training and rollback | CLI | `scripts/local_lora_training.py` | `tests/test_local_lora_training.py` |
| License/model/provenance gates | CI and CLI | `security/`, `scripts/` | `tests/test_licensing.py`, `tests/test_license_scan.py`, `tests/test_provenance.py` |
| Browser smoke coverage | Playwright against Chat and Studio | Real FastAPI app on an isolated workspace | `apps/web/e2e/app.spec.mjs` |

| Inline completions | Studio ghost text; Code-OSS provider | `/api/ai/complete` | `tests/test_completions.py` |
| Explicit @-mention context | Chat messages | `services/api/context_refs.py` | `tests/test_context_refs.py` |
| Project instruction files | Every agent prompt | `services/api/rules.py`, `GET /api/projects/{project}/instructions` | `tests/test_rules.py` |
| Turn-level undo | Studio **Undo AI turn** | `/api/studio/turns/revert` | `tests/test_turns.py` |
| Approved commands | Studio **Run command** | `/api/execution/command/*` | `tests/test_commands.py` |
| Model picker and usage | Studio model select; Code-OSS chat | `/api/models`, `/api/models/{project}/usage` | `tests/test_models.py` |
| MCP tool servers | API `/docs` | `/api/mcp/*` | `tests/test_mcp.py` |
| Git branch, commit and PR prep | API `/docs` | `/api/git/*` | `tests/test_gitflow.py` |
| Worktree test loop | `POST /api/agents/execute` | `services/api/executor.py` | `tests/test_agent_loop.py` |

## Deliberately not in the browser

- **Arbitrary shell execution** is not exposed. Only the allowlisted, approval-gated Docker command set is callable.
- **Direct model file writes** are disabled. AI output must pass the Studio or batch approval path.
- **Model training** is a separate CLI operation with an explicit consent flag and reviewed model license.
- **Installer signing, notarization and hosted multi-user operation** are not implemented.

The browser API documentation at `/docs` requires the same administrator bearer token for protected endpoints; it is a local developer surface, not a public deployment.
