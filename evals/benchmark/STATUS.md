# Agent benchmark status

**Blocked: no model is configured in this workspace.** `MODEL_API_KEY`,
`MODEL_NAME`, `LOCAL_MODEL_ONLY` and a local OpenAI-compatible server are all
absent, and no GPU is available. There is therefore **no real agent score** to
record. The committed `baseline.json` remains a 0/30 starter baseline, not a
model result.

The model-backed agent is implemented in `scripts/benchmark_agent.py`. Once a
model is configured (environment or `.env`, never committed), run:

```bash
python scripts/run_benchmark.py \
  --agent-command "$PWD/.venv/bin/python $PWD/scripts/benchmark_agent.py" \
  --json evals/benchmark/agent.json \
  --markdown evals/benchmark/AGENT.md
```

The runner supplies `BENCHMARK_PROMPT` and puts each task in a disposable
directory. The agent returns complete file contents as JSON; only relative,
non-`.git` paths are accepted. If the model is missing, the agent exits non-zero
and no score is fabricated.

To record the gate, set the model in the environment or project secrets, rerun
the command above, and commit `agent.json`. Until then, do not quote 0/30 as an
agent result.
