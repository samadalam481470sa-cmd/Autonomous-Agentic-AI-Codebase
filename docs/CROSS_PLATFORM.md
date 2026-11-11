# Windows, macOS and Linux

The application is designed to run from a source checkout on Windows 10/11, macOS (Intel and Apple Silicon), and Linux, and to package the Electron desktop app for those platforms.

## Tested by CI

The `Verify` workflow runs the Python and Node test suites plus the Playwright browser smoke suite on `ubuntu-latest`, `windows-latest`, and `macos-latest`. The desktop packaging workflow builds:

| Platform | Installer | Runner |
| --- | --- | --- |
| Windows | NSIS `.exe` | `windows-latest` |
| macOS | `.dmg` | `macos-latest` |
| Linux | `.AppImage` | `ubuntu-latest` |

A successful package build does not mean an installer is signed, notarized, clean-machine verified, or safe for broad distribution.

## Source setup

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m uvicorn services.api.main:app --reload
```

If script execution is disabled, use `.venv\Scripts\activate.bat` from `cmd.exe` or run `.venv\Scripts\python.exe -m uvicorn services.api.main:app --reload` directly.

### macOS and Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
python -m uvicorn services.api.main:app --reload
```

The API and web UI bind to `127.0.0.1:8000`. Do not expose them to a network.

## Platform-specific behavior

- **Desktop binary names.** The Electron shell looks for `agentic-backend.exe` and `agentic-runtime.exe` on Windows, and `agentic-backend`/`agentic-runtime` elsewhere. PyInstaller and Cargo produce those names natively.
- **macOS microphone.** `NSMicrophoneUsageDescription` is declared in the packaged app. The user must still grant microphone access, and the optional `whisper.cpp` server must be installed separately.
- **Browser audio.** The chat page uses the standard `AudioContext` with a WebKit fallback. Localhost is a secure context in current Chromium and Safari browsers.
- **Docker paths.** The isolated execution endpoints normalize Windows bind paths to forward slashes before invoking Docker Desktop. Docker Desktop must be running Linux containers.
- **Local process cleanup.** `scripts/local_stack.py` starts each service in its own process group. On Windows it stops the full tree with `taskkill /T`; on POSIX it signals the process group, so `cargo run` and model child processes do not survive Ctrl+C.
- **GPU training.** CUDA and ROCm are supported on Windows and Linux; Apple Silicon uses PyTorch MPS. The training loop allocates tensors on the detected device rather than assuming CUDA. CPU-only training is refused.
- **SQLite paths.** Feedback database URIs use `Path.as_uri()`, which handles Windows drive letters and POSIX paths.
- **Line endings and paths.** Repository code uses UTF-8 text and forward-slash paths in metadata; Python and Node APIs resolve native paths at runtime.

## Not yet certified

- No signed or notarized installers.
- No clean-machine installer testing on all three operating systems.
- No Windows ARM64 or universal macOS artifact in the current workflow.
- GPU drivers, `llama.cpp` binaries, `whisper.cpp`, Docker, Cargo and model weights are user-installed prerequisites.
- The CI matrix validates source tests and packaging configuration; it does not validate a real GPU, microphone, or desktop installation.
