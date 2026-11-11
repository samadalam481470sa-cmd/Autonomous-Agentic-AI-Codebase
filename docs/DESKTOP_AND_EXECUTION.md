# Desktop, VS Code and isolated execution

## Desktop packaging
The Electron client opens the local Python backend at http://127.0.0.1:8000/studio. It is **not** a standalone bundled backend or full VS Code clone. Start the Python backend separately.

```bash
cd apps/desktop
npm install
npm start
npm run package:win   # Windows installer (on supported Windows build environment)
# or npm run package:mac / npm run package:linux
```

Artifacts are produced in `apps/desktop/dist`. The packaging workflow builds these targets on Windows, macOS and Linux GitHub runners. Installers are unsigned and not notarized, and have not been clean-machine certified; do not distribute them as trusted signed releases.

macOS builds match the architecture of the build machine. Build separately on Intel and Apple Silicon hosts if both architectures are required. The macOS bundle declares microphone usage for the optional local voice transcription feature.

## VS Code extension
`apps/vscode-extension` provides commands that open the local chat and code studio. It does not yet provide inline completions, repository indexing, code actions or a native VS Code editor integration.

## Isolated execution
Set `ENABLE_ISOLATED_EXECUTION=1` only on a **dedicated trusted host** with Docker installed. The API `POST /api/execution/run` requires `Authorization: Bearer <AGENT_ADMIN_TOKEN>` and `X-Confirm-Execution: approve`. It only accepts a small command allowlist and runs a non-root container with no network, dropped capabilities, read-only root and workspace, and resource limits.

**Security limitations:** The Docker daemon is privileged and containers are not VM-grade isolation. Do not expose the host Docker socket to the app container. The host-mounted workspace can contain malicious files, and Docker/container escape vulnerabilities remain possible. Never run arbitrary user workloads on a machine holding secrets. The default execution mode is disabled.

## Important
Existing agent file-write tools are still not wired to the Studio approval flow. The system must not be advertised as safe for unrestricted autonomous execution. See security/THREAT_MODEL.md.
