# Continuous local learning

Aetherion can learn from the interactions it already serves without sending data
to a provider and without giving the model the ability to write files or run
commands.

## RAG in search

`POST /api/ai/search` now returns both ranked matches and a grounded RAG packet:

- hybrid vector + FTS5 matches;
- feedback and learned-reranker scores;
- a budgeted, deduplicated context block wrapped in
  `<untrusted_repository_context>`;
- citations with redaction and prompt-injection risk counts.

The packet is built from the same result set, so enabling it does not run a
second retrieval pass. `/api/ai/ask` remains the endpoint that sends the packet
to the configured model.

## What is learned

The learner records redacted prompts, answers and citations in
`workspaces/<project>/.agent/learning.sqlite3` when capture is enabled. Secrets
are replaced before storage. Each explicit 👍/👎 on an answer, or a citation
vote, becomes a labelled query/path example.

A pairwise learning-to-rank model is trained on bounded features:

- fused, semantic and lexical scores;
- query overlap with the path and excerpt;
- existing path feedback;
- test-file and path-depth priors.

Candidates are evaluated with NDCG@5 on a chronological holdout plus
self-supervised queries derived from indexed filenames. A candidate is promoted
only when it beats the active model by `AETHERION_LEARN_MIN_GAIN` and does not
regress the probe score. Every model is stored with its metrics; the dashboard
can roll back to the previous version.

This is inspectable retrieval learning. Foundation-model weights are handled
separately by the opt-in GPU LoRA path below.

## Optional GPU weight training

The existing `scripts/local_lora_training.py` trainer is now integrated behind an
explicit consent gate. It consumes accepted answers exported from the lifelong
interaction store into `.agent/feedback.sqlite3`, uses a deterministic 20%
held-out split, and activates an adapter only when candidate loss improves over
the base model by `AETHERION_LORA_MIN_GAIN`. A run requires:

- `AETHERION_LORA_TRAIN=1`;
- a detected local CUDA/ROCm/MPS device and `requirements-training.txt` installed;
- at least 12 👍 answers;
- a local Hugging Face-format model directory, reviewed model id and license;
- explicit consent in `POST /api/learning/{project}/gpu-training`.

The trainer runs as a fixed-argument subprocess, never through a shell. Model
licenses are checked by the shared registry before PyTorch loads the model. The
adapter is versioned under `.agent/models/versions/` and can be rolled back. It
is **not** loaded into llama.cpp automatically; wire the adapter into a compatible
local runtime deliberately after inspecting its held-out metrics.

This is deliberately not part of the 24/7 CPU loop: a second GPU job would compete
with always-on inference and raise temperatures. Start it manually when the
machine is idle and on AC power.

## The 24/7 loop

`services/api/lifelong.py` runs a daemon while the local app is open. The
launcher enables it by default; a persisted pause switch is available in the
dashboard.

Each cycle:

1. checks the thermal governor and GPU temperature;
2. optionally indexes changed project files;
3. trains from any new feedback;
4. records the cycle result and sleeps for `AETHERION_LEARN_INTERVAL` seconds.

The learner is deliberately CPU-light. A 24/7 local model already owns the GPU;
a second GPU training job would compete with inference and raise temperatures.
The learner therefore yields to inference and only runs when the device
admits work. Set `AETHERION_LEARN_AC_ONLY=1` to skip cycles on battery.

## Controls

- `GET /api/learning/continuous/status?project=...`
- `POST /api/learning/continuous/start`
- `POST /api/learning/continuous/pause`
- `POST /api/learning/continuous/tick`
- `POST /api/learning/{project}/train`
- `POST /api/learning/{project}/rollback`
- `POST /api/learning/{project}/interactions/{id}/rate`
- `GET /api/learning/{project}/gpu-training`
- `POST /api/learning/{project}/gpu-training`
- `POST /api/learning/{project}/gpu-training/rollback`

The dashboard **Learning** page shows loop state, GPU/power telemetry, feedback
counts, active-model NDCG, candidates that were rejected, and recent redacted
interactions with rating controls.

## Privacy and limits

- No network calls, telemetry or cloud storage.
- Capture can be disabled with `AETHERION_LEARN_CAPTURE=0`.
- Prompts and responses are capped and redacted; databases are excluded from the
  downloadable bundle and from git.
- Autonomous learning only changes retrieval ranking. File writes, shell
  commands, agent-run approval and execution remain separate, gated actions.
- A promoted model can overfit a very small feedback set. The holdout gate and
  rollback exist for that reason; inspect metrics before relying on it.
