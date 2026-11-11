# Polyglot coding and the always-on local worker

This build can work in any language the owner's computer can build, and it can
keep working in the background while that computer is on. Both features are
local-first: no cloud compiler, no remote execution and no bundled model.

## What "any language" means here

`services/api/toolchains.py` is a declarative registry of 64 language families.
Each entry lists:

- executables to probe (`gcc`, `cargo`, `dotnet`, `kotlinc`, `sqlite3`, …)
- an optional single-file `check` command
- optional `compile` + `execute` templates for compiled languages
- optional project-level `build` and `test` commands
- an install hint used when the toolchain is missing

Templates are argv lists and are executed **without a shell**. A file name, a
language name or a model response can never append another command. Child
processes receive a minimal environment; the administrator token and model API
key are not inherited.

Supported built-ins include Python, JavaScript, TypeScript, Rust, Go, Java,
Kotlin, Scala, C, C++, C#, Swift, Objective-C, Dart, Ruby, PHP, Perl, Lua, R,
Julia, Haskell, Elixir, Erlang, OCaml, F#, Clojure, Groovy, shell, PowerShell,
SQL, Zig, Nim, Crystal, D, Fortran, Pascal, Ada, COBOL, assembly (NASM),
Solidity, Verilog, GLSL, MATLAB/Octave, TeX, Terraform, protobuf, Nix, plus
markup/data formats that need no compiler.

Anything else can be added at runtime without editing source:

```bash
curl -X POST http://127.0.0.1:8000/api/polyglot/register \
  -H "Authorization: Bearer $AGENT_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "language": "mylang",
    "extensions": [".ml"],
    "probes": [["mylangc", "--version"]],
    "check": ["{exe}", "-check", "{file}"],
    "compile": ["{exe}", "-o", "{out}/program", "{file}"],
    "execute": ["{out}/program"],
    "install": "Install mylang from the vendor"
  }'
```

Definitions are validated (name, extension, placeholder and argument limits) and
persisted to `POLYGLOT_TOOLCHAINS_PATH`. `GET /api/polyglot/languages` reports
what is actually installed on this machine and what is missing.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/polyglot/languages` | Registry plus detected executables and versions |
| `POST /api/polyglot/detect` | Language breakdown of a project and missing toolchains |
| `POST /api/polyglot/register` | Add a custom language definition |
| `POST /api/polyglot/scaffold` | Write a runnable starter project and verify it |
| `POST /api/polyglot/run` | Run `check`, `build`, `test` or `run` for a real file |
| `POST /api/polyglot/solve` | Generate → compile/test → retry, then propose or apply |
| `GET /api/worker/status` | Worker decision, queue, GPU, power and policy |
| `POST /api/worker/jobs` | Enqueue durable work |
| `POST /api/worker/pause` / `resume` / `start` / `stop` | Runtime controls; `stop` is the persisted kill switch |
| `POST /api/worker/policy` | `always`, `ac_only`, `manual`, `off`, active hours, GPU temperature cap |

A browser control page is served at **http://127.0.0.1:8000/control**. It needs
the same administrator token as Studio.

## The autonomous loop

`POST /api/polyglot/solve` chooses a language (explicit, project-dominant or
keyword-based), asks the configured model for one complete file, writes it to a
temporary trial directory, and runs the real toolchain. On failure the compiler
or interpreter output is fed back and the model retries up to three times. A
passing candidate is stored as a normal multi-file proposal and is applied only
when `AGENT_AUTONOMY=1` or the caller explicitly requests and approves the
change. Applied files get the same SQLite checkpoints as Studio edits.

The desktop build sets `AGENT_AUTONOMY=1` and `AGENT_HOST_TOOLCHAIN=1`. A
standalone API leaves both off: file changes then require
`X-Confirm-Change: approve`, and builds/runs require
`X-Confirm-Execution: approve`. Host execution is inherently powerful — the
commands are this computer's own compilers and interpreters, not a sandbox.

## Always-on work

`services/api/worker.py` provides a SQLite-backed queue with atomic claims,
retry backoff, cancellation, stale-job recovery and payload limits. The worker
thread starts only when `AGENT_WORKER_ENABLED=1`, which the desktop app sets. It
keeps running while the machine is powered on; it stops with the process, with
`POST /api/worker/stop`, or when the machine is shut down. Pausing retains
queued work.

Scheduling is a pure decision, covered by tests:

- `always` (default) — run whenever this computer is on
- `ac_only` — only while mains power is connected
- `manual` — only when explicitly started
- `off` — never
- `AGENT_WORKER_ACTIVE_HOURS` (e.g. `22-7`) limits the window
- `AGENT_WORKER_MAX_GPU_TEMP_C` pauses claims when GPU telemetry reaches the cap

GPU utilisation is read from `nvidia-smi` or `rocm-smi` when installed. Apple
Silicon is detected but not measured, because `powermetrics` needs privileges.
Local GPU acceleration itself comes from llama.cpp's backend; the worker does
not bundle drivers or weights and does not claim GPU use when it cannot verify
it. Idle CPU/GPU time still consumes electricity: use `ac_only`, active hours,
pause or stop on battery- or thermally-constrained machines.

## Sign-in autostart

The desktop setup screen has an "always-on" checkbox backed by
`apps/desktop/energy.cjs` and `app.setLoginItemSettings`. For a headless install:

```bash
python scripts/install_autostart.py --print     # inspect the unit
python scripts/install_autostart.py --install   # write ~/.config/systemd/user/agentic-worker.service
systemctl --user daemon-reload
systemctl --user enable --now agentic-worker
```

macOS writes a LaunchAgent plist; Windows prints an `schtasks /SC ONLOGON`
command. Secrets belong in `~/.config/agentic-ai/worker.env` (referenced by the
unit), never in the unit itself.

## Verification status

Automated tests cover registry shape, aliases, path containment, argv-only
planning, real Python check/run, real C compile/run when `gcc` exists, custom
language persistence, queue lifecycle and retries, scheduling policies, the
worker API, and the solve loop with an injected model response. Commands for
uninstalled toolchains are not executed in CI; their install hints are reported
instead. No certified GPU inference run, clean-machine installer test or
language-server integration is claimed.
