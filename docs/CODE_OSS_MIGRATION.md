# Code-OSS migration milestone — upstream workbench integration

The existing desktop app is an Electron + Monaco **experimental fallback**. This migration adds a **reproducible pinned Code-OSS source overlay and a functioning-source local AI sidebar extension**. It does *not* claim the Code-OSS desktop app was compiled, signed or installed in CI yet. It also does not copy Microsoft's proprietary VS Code distribution or use the Microsoft Marketplace.

## Upstream and license provenance

- Base: `microsoft/vscode`, MIT license, Git tag `1.144.0` (October 28, 2026).
- **Pin:** `2c33b50b16c472efe58357d1d2a8a5414bc23fbf`. The preparation script checks the exact SHA before modifying a source tree.
- The Code-OSS tree is an **upstream checkout**, *not yet a fork in the GitHub repository graph*, and lives in `.local/code-oss` (gitignored). A future repository fork / merge strategy requires a separately authorized fork action.
- First-party overlay source lives in `code_oss_integration/extension/`. Do not count upstream LOC as original authored code.
- Product identity uses independent names, protocol, data folders, platform IDs, and Windows registration IDs. Gallery endpoints use the [official Open VSX adapter](https://github.com/eclipse-openvsx/openvsx/wiki/Using-Open-VSX-in-VS-Code).
- Upstream bundled branding assets and the whole set of vendor URLs have **not** been audited or replaced; do not release the fork until branding, legal, update and telemetry review are complete.
- Pin changes require deliberate upstream review and a new migration test run. No auto-update or silent branch rebasing is configured.

## Prepare locally

With Python 3.12+, Node.js, Git, the build tools required by upstream Code-OSS and sufficient local disk space:

```bash
python scripts/code_oss_migrate.py --clone --source .local/code-oss
python scripts/code_oss_migrate.py --verify --source .local/code-oss
```

The script checks out the upstream MIT source at the pinned tag, validates the commit, patches `product.json`, and places the extension in `extensions/agentic-local/`. It refuses an unreviewed upstream commit. It is safe to re-run on the exact pinned checkout, but it changes files in that separate checkout.

For an interactive source build, follow Microsoft's [Code-OSS source build prerequisites](https://github.com/microsoft/vscode/wiki/How-to-Contribute). On Linux/macOS the development command is typically:

```bash
cd .local/code-oss
npm install
./scripts/code.sh --extensionDevelopmentPath="$(pwd)/extensions/agentic-local"
```

This local development workflow is not a tested cross-platform installer or signed distributable. The browser/Monaco version continues to be packaged by the original desktop workflow. Windows build specifics follow the upstream Wiki.

## Connect the pre-existing local AI services

The Code-OSS extension invokes the project's existing **FastAPI** service, not a separate hosted API. For a local model, run a compatible `llama-server` on `127.0.0.1:9931` and the Rust gateway on `127.0.0.1:8088`. See [Rust and llama.cpp guide](RUST_LLAMA_INTEGRATION.md). Start FastAPI manually with `LOCAL_MODEL_ONLY=1` and the Rust gateway URL set as `LOCAL_MODEL_BASE_URL=http://127.0.0.1:8088/v1`:

```bash
export AGENT_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export LOCAL_MODEL_ONLY=1
export LOCAL_MODEL_BASE_URL=http://127.0.0.1:8088/v1
export LOCAL_MODEL_NAME=local-model
python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

Run these commands in the repository root, using the appropriate environment-variable syntax for your OS. Copy the generated token privately into the extension via **Local AI: Connect to This Computer**. The extension saves the token using VS Code `SecretStorage`; the token is **not sent to the webview**, written to workspace settings, or uploaded to a cloud server. Do not share the token.

The original experimental Electron desktop generates a random backend token internally; that token is not intended for this separate Code-OSS build. Start the backend explicitly with a known secret as above. Do not run two local backends on port 8000.

## Working first-party extension surface

- Local AI sidebar via workbench activity bar.
- Opt-in stream of text replies from `/api/chat/stream` through the Rust gateway.
- **Local AI: Explain Selection** adds only the explicitly selected code to a chat draft.
- Stop button aborts the HTTP stream.
- Fixed/validated loopback-only endpoint and locally stored credentials.
- Content is rendered with `textContent` and a nonce-bearing restrictive Content Security Policy; no remote scripts or active HTML content are injected.
- Existing Code-OSS native explorer, terminal, debugger, source-control and extension host come from the upstream workbench source, but have **not yet passed an assembled-build smoke test** in this product.

## Not yet migrated

- The local editor/agent approved-diff workflow remains in the FastAPI Studio UI.
- No Tab completion, inline Cmd+K diffs, native VS Code change-approval UI, full shared agent harness or codebase symbol search is integrated into Code-OSS yet.
- No Code-OSS installer has been compiled or published by these changes.
- Upstream VS Code extensions are not guaranteed all compatible with independent forks. Open VSX is supported as the preferred extension source.
- No automatic model installer, runtime GPU benchmark, cross-platform signing/notarization, multi-process isolation or durable agent state-machine recovery.

## Test and release gates

Main CI tests the first-party patcher, extension JSON and SSE parser without downloading upstream code. The **Code-OSS upstream overlay validation** workflow can be triggered manually to download the exact pinned release, apply the patch, and verify the resulting source tree. Neither workflow should be labeled a complete IDE parity or Code-OSS production release test.
