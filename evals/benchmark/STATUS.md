# Agent benchmark status

The local cloud workspace has no `MODEL_API_KEY`, no local OpenAI-compatible
server and no GPU, so a local score cannot be measured here. The committed
`baseline.json` is a **starter baseline of 0/30**, not a model result.

GitHub Models was retired on July 30, 2026, so its built-in token path cannot be
used. The [benchmark workflow](../.github/workflows/benchmark.yml) checks for a
repository `MODEL_API_KEY` secret and skips cleanly when it is absent; when a
real OpenAI-compatible model is configured (optionally with `MODEL_BASE_URL` and
`MODEL_NAME` repository variables), it writes and commits `agent.json` and
`AGENT.md`. If the model cannot run for every task, the harness exits non-zero
and records nothing.

For a local model configured in the environment or `.env` (never committed):

```bash
python scripts/run_benchmark.py \
  --agent-command "$PWD/.venv/bin/python $PWD/scripts/benchmark_agent.py" \
  --json evals/benchmark/agent.json \
  --markdown evals/benchmark/AGENT.md
```

The runner supplies `BENCHMARK_PROMPT` and puts each task in a disposable
directory. The agent returns complete file contents as JSON; only relative,
non-`.git` paths are accepted. If the model is missing, the agent exits non-zero
and no score is fabricated. Do not quote 0/30 as an agent result.
