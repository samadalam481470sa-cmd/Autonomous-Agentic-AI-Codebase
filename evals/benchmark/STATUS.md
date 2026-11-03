# Agent benchmark status

The local cloud workspace has no `MODEL_API_KEY`, no local OpenAI-compatible
server and no GPU, so a local score cannot be measured here. The committed
`baseline.json` is a **starter baseline of 0/30**, not a model result.

The [benchmark workflow](../.github/workflows/benchmark.yml) runs the same 30
tasks in CI with GitHub Models (`openai/gpt-4o-mini`) using the repository's
built-in `GITHUB_TOKEN` and `models: read`. It writes `agent.json` and `AGENT.md`,
then commits them back with `[skip ci]`. If the model cannot run for every task,
the harness exits non-zero and records nothing.

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
