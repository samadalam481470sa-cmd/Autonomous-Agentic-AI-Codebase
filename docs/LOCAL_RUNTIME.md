# Run Aetherion OmniForge on your own computer

Aetherion is local-first. The API, dashboard, database and model gateway run on
your CPU, GPU and RAM. There is no telemetry, no cloud account and no required
data centre. Docker, PostgreSQL, Redis and Kubernetes are only for the separate
hosted mode and are not needed here.

## Requirements

| Item | Minimum | Recommended |
| --- | --- | --- |
| Python | 3.11 | 3.12 |
| RAM | 8 GB | 16 GB or more |
| Disk | 2 GB free | 10 GB free for models |
| GPU | Not required | NVIDIA 8 GB+ VRAM, AMD ROCm, or Apple Silicon |
| OS | Windows 10, macOS 12, Linux | Current releases |

The dashboard bundle is committed and prebuilt, so Node.js is not required to
run the application.

## Download and start

1. Download `aetherion-omniforge-<version>.zip` from the repository's **Actions
   artifacts** or a tagged **Release**, and verify it:

   ```bash
   sha256sum -c aetherion-omniforge-<version>.zip.sha256
   ```

2. Unzip and start:

   ```bash
   unzip aetherion-omniforge-<version>.zip
   cd aetherion-omniforge-<version>
   ./run.sh            # Linux / macOS
   ```

   ```bat
   run.bat
   ```

3. The launcher creates `.venv`, installs the local Python dependencies, prints
   an administrator token and the dashboard URL, and opens it. It uses
   `http://127.0.0.1:8000` when that port is free and the next free loopback
   port when it is busy, so a previous run does not block startup.

The first run needs network access once to install FastAPI, Uvicorn, HTTPX and
Pydantic. After that the app runs offline; the dashboard is prebuilt and no
model download happens unless you ask for one.

Paste the token into the dashboard. It is generated per run unless you set
`AGENT_ADMIN_TOKEN` or pass `--token`.

To keep everything on this machine even when a hosted model key exists, the
launcher sets `LOCAL_MODEL_ONLY=1` by default.

### Launcher options

```bash
python aetherion.py --check            # hardware, thermal and backend report
python aetherion.py --no-open          # do not open a browser
python aetherion.py --port 8123        # exact loopback port; errors if busy
python aetherion.py --hours 12         # keep-awake budget
python aetherion.py --no-keep-awake    # allow normal sleep
```

The launcher refuses non-loopback bind addresses. Without `--port`, a busy
`8000` is skipped automatically; the printed URL and token are for the new
process. An explicit `--port` never falls back, so a conflict is reported.

## Local models

The gateway speaks the OpenAI-compatible `/v1` protocol. Any of these work:

| Backend | Default endpoint | Start |
| --- | --- | --- |
| Ollama | `http://127.0.0.1:11434/v1` | `ollama serve` |
| llama.cpp server | `http://127.0.0.1:9931/v1` | `llama-server -m model.gguf --port 9931` |
| LM Studio | `http://127.0.0.1:1234/v1` | Start the local server in the app |

The **Device** page probes loopback endpoints only and shows which models are
loaded. It recommends a quantized coding model from detected VRAM or unified
memory:

| Available memory | Recommended model | Approximate VRAM |
| --- | --- | --- |
| 24 GB+ | `qwen2.5-coder:32b` (Q4) | 20 GB |
| 14–24 GB | `qwen2.5-coder:14b` (Q4) | 9 GB |
| 5.5–14 GB | `qwen2.5-coder:7b` (Q4) | 4.7 GB |
| 3.5–5.5 GB | `qwen2.5-coder:3b` (Q4) | 2 GB |
| CPU only, 16 GB RAM | `qwen2.5-coder:7b`, `gpu_layers=0` | system RAM |
| CPU only, 8 GB RAM | `qwen2.5-coder:3b`, `gpu_layers=0` | system RAM |

For Ollama:

```bash
ollama pull qwen2.5-coder:7b
export LOCAL_MODEL_ONLY=1
export LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
export LOCAL_MODEL_NAME=qwen2.5-coder:7b
```

Then start the app. The exact snippet is on the Device page and can be copied
with one button. Model licences vary: check the model card before commercial
use, and keep the provenance entry in `third_party/oss_registry.json`.

## Thermal governor

The governor runs on the API process and is also sampled by a background thread
while the app is open.

- **Sensors**: Linux `thermal_zone*` and `hwmon`, NVIDIA `nvidia-smi`, AMD
  `rocm-smi`. Apple Silicon exposes no public per-core temperature to
  unprivileged processes, so macOS often reports monitor-only mode.
- **Signal**: maximum current temperature, a 30% exponentially weighted moving
  average, the slope in °C per minute, and a predicted temperature 1.5 minutes
  ahead.
- **States**: `normal` → `warm` at 78 °C → `hot` at 86 °C → `critical` at 92 °C.
  A rising prediction can enter `hot` or `critical` before the raw value reaches
  the limit. After a hot period the governor stays in `cooldown` for 30 seconds
  and only resumes below 70 °C.
- **Effect**: at `hot` or above, advancing a multi-agent run returns HTTP 409
  with `Retry-After` and the run stays queued. At `critical`, the keep-awake hold
  is also released. A battery below 15% while unplugged pauses new model calls.
- **No sensors**: the governor reports `unknown` and monitor-only mode. It never
  invents a temperature and never blocks work without evidence.

Configure it with environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEVICE_TEMP_WARN_C` | `78` | Warm threshold |
| `DEVICE_TEMP_HOT_C` | `86` | Pause new model calls |
| `DEVICE_TEMP_CRITICAL_C` | `92` | Release keep-awake |
| `DEVICE_TEMP_RESUME_C` | `70` | Resume below this after cooldown |
| `DEVICE_COOLDOWN_SECONDS` | `30` | Minimum cooling period |
| `DEVICE_SAMPLE_SECONDS` | `5` | Monitor interval |
| `DEVICE_PREDICT_MINUTES` | `1.5` | Prediction horizon |
| `DEVICE_MIN_BATTERY_PERCENT` | `15` | Battery safety floor |
| `DEVICE_SESSION_MAX_HOURS` | `8` | Displayed session budget |
| `DEVICE_THERMAL_GUARD` | `1` | Set `0` to disable the agent gate |
| `DEVICE_DB_PATH` | `./database/device.sqlite3` | Thermal event ledger |

Transitions are appended to a local SQLite ledger (last 500 entries) and
surfaced on the Device page.

## Keep-awake and long sessions

| OS | Mechanism | Notes |
| --- | --- | --- |
| macOS | `caffeinate -dimsu` | Prevents idle, system and disk sleep |
| Linux | `systemd-inhibit --what=idle:sleep` | Needs a systemd user/system session |
| Windows | `SetThreadExecutionState` | Holds system and display awake |
| Other | None | Reported as unsupported; work still runs |

The launcher holds the machine awake for 8 hours by default (`--hours`). The
hold has an expiry and is released when:

- you toggle it off on the Device page,
- the TTL expires,
- the API shuts down,
- the governor reaches `critical`.

The dashboard shows uptime, time held awake and the remaining TTL. Keep the
machine on a hard surface with clear vents; a cooling pause is working as
designed, not a failure.

## Build the downloadable bundle

```bash
cd apps/dashboard && npm ci && npm run build && cd ../..
python scripts/package_local.py --output-dir dist
```

The builder writes:

- `dist/aetherion-omniforge-<version>.zip` — prebuilt dashboard, Python
  services, launchers, docs, tests, `QUICKSTART.txt` and `MANIFEST.json` with a
  SHA-256 for every file;
- `dist/aetherion-omniforge-<version>.zip.sha256`.

It refuses to build when the dashboard is missing or not built, and it excludes
`.venv`, `node_modules`, caches, databases, logs and `.env*` files. The archive
is pure Python plus static assets, so the same file runs on Linux, macOS and
Windows.

`.github/workflows/local-bundle.yml` rebuilds and tests the bundle on demand and
on `v*` tags, uploads it as an Actions artifact, and attaches the zip and
checksum to the GitHub Release.

## Security

- Loopback bind only; cross-origin writes are rejected by the security
  middleware.
- Bearer token on every API call, optional TOTP (`AGENT_TOTP_SECRET`), brute
  force lockouts, rate limits and an audit trail.
- No automatic updates. Download and verify releases yourself.
- Thermal and hardware data stay in local SQLite; nothing is uploaded.
- The launcher prints the token once to the terminal. It is never written to a
  file in the bundle.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Port 8000 is already in use; using 8001 instead` | Expected after a previous run; open the printed URL and use the new token |
| `Port ... is already in use` with explicit `--port` | Stop the other process or choose a free port, for example `--port 8123` |
| `/dashboard` returns 503 | Rebuild the dashboard or use a release bundle with `dist/` |
| Device page says no sensors | Expected on many desktops and VMs; monitor-only mode |
| Keep-awake shows unsupported | Linux needs `systemd-inhibit`; install `systemd` or use macOS/Windows |
| No local backend listed | Start Ollama or llama.cpp and refresh |
| Agent advance returns 409 | Device is hot or cooling; wait for the `Retry-After` period |
| Model too slow | Use the smaller recommendation or reduce `LOCAL_CONTEXT_CHAR_BUDGET` |

## Honest limits

Thermal behaviour depends on what the firmware exposes; some machines report no
useful sensors, and no user-space program can guarantee cooling. The governor
reduces risk, it does not replace adequate hardware cooling. Local models are
smaller than hosted frontier models, and output quality depends on the model you
install. The Code-OSS production build, sandboxed execution and hosted control
plane described in the framework remain separate, unfinished phases.
