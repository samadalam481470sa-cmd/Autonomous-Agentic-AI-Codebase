# Coding benchmark

30 deterministic tasks (20 Python, 10 JavaScript) with a deliberately failing
starter. The runner copies one task into a disposable temporary directory,
optionally runs an agent command there, and then runs the task's test with no
shell and a timeout.

## Commands

```bash
# Starter baseline (recorded result: 0/30)
python scripts/run_benchmark.py \
  --json evals/benchmark/baseline.json \
  --markdown evals/benchmark/BASELINE.md

# A real agent: it runs in the task copy and reads the prompt from the environment
python scripts/run_benchmark.py --agent-command /path/to/agent \
  --json evals/benchmark/agent.json

# Gate a measured run
python scripts/run_benchmark.py --require-pass 24
```

The agent command receives `BENCHMARK_TASK_ID` and `BENCHMARK_PROMPT`, and may
only edit files in its current working directory. The runner does not provide
network access or a model key; the agent is responsible for its own sandbox.

## Honest status

`baseline.json` is a **starter baseline**, not a model score. It proves every
task starts red and the harness is working.

The first real local measurement used `Qwen2.5-Coder-0.5B-Instruct Q4_K_M` on
CPU (llama.cpp, 2 threads): **10/30**, with one agent failure on `js-chunk`.
Full results are in `agent.json` and `AGENT.md`. This is a small-model result,
not a frontier-model score; do not quote the 0/30 starter baseline as an agent
result, and do not treat 10/30 as production capability.
