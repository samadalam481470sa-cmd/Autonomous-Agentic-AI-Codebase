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
task starts red and the harness is working. No model/agent has been measured
here, so the Phase 0 gate (“held-out benchmark with a baseline”) has the tasks
and harness but is not passed. Do not quote 0/30 as an agent result.
