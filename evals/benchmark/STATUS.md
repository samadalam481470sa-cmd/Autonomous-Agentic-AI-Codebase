# Agent benchmark status

**Measured on 2026-11-03 with a real local model.** The agent scored **10/30**
with `Qwen2.5-Coder-0.5B-Instruct Q4_K_M` on CPU (llama.cpp, 2 threads). The
starter baseline is **0/30**. One task (`js-chunk`) had an agent failure: the
model returned a placeholder twice and was correctly rejected.

This is a small CPU model, not a frontier cloud model. It proves the harness,
agent file-write loop and scoring path work end to end and gives a measured
baseline; it does **not** establish production capability.

Artifacts:

- `agent.json` — full per-task result, including the agent failure
- `AGENT.md` — task table and model label

Reproduce locally with an OpenAI-compatible model:

```bash
python scripts/run_benchmark.py \
  --agent-command "$PWD/.venv/bin/python $PWD/scripts/benchmark_agent.py" \
  --label "your-model" \
  --json evals/benchmark/agent.json \
  --markdown evals/benchmark/AGENT.md
```

The runner supplies `BENCHMARK_PROMPT` and puts each task in a disposable
directory. Single-file tasks use raw-code output; multi-file tasks use JSON.
Only relative, non-`.git` paths are accepted, and placeholders/unchanged files
are rejected. If the model fails for every task, the harness exits non-zero and
does not pretend the result is a score.

GitHub Models was retired on July 30, 2026. The [benchmark workflow](../.github/workflows/benchmark.yml)
uses a repository `MODEL_API_KEY` secret and skips cleanly when it is absent;
when configured, it writes and commits the measured score. A frontier-model
score remains open.
