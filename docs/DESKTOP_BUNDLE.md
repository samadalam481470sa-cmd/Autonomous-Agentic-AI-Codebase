# Desktop bundled backend (experimental)

The desktop installer now includes a PyInstaller-built Python FastAPI backend. When opened, Electron launches it on 127.0.0.1:8000, generates a random administrator token, and stores projects and SQLite history in the app's user-data directory. It stops the backend on app exit.

Build on the target operating system:
```bash
python -m pip install -r requirements.txt pyinstaller
python scripts/build_backend.py
cd apps/desktop
npm install
npm run package:win  # or package:mac / package:linux
```

A manual GitHub Actions workflow attempts packaging for all three operating systems. Packages are unsigned and not production verified.

**Not bundled:** llama.cpp, Rust gateway, GPU drivers, model weights. The backend defaults to local-only mode and expects a Rust gateway at 127.0.0.1:8088/v1. The editor works without a model but AI chat will not work until a local inference server is configured. No hardware auto-detection or model installation wizard yet. GPU memory requirements vary by model and hardware.

**Security limitations:** The desktop's token is injected into its own restricted renderer; no network access should be allowed to the local backend from untrusted web content. Other local processes could still reach unauthenticated model endpoints. A production release needs per-session IPC authentication, dynamic ports, binary signing, platform smoke tests, update verification and hardened process lifecycle management.
