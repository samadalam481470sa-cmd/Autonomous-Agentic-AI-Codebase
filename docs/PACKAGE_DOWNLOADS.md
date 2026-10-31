# Where to download

## GitHub Packages
The scoped JavaScript API client is published by `.github/workflows/publish-client-package.yml`. It is a developer dependency, **not** a standalone application.

## Desktop installer artifacts
Go to [Desktop packaging Actions](https://github.com/samadalam481470sa-cmd/Autonomous-Agentic-AI-Codebase/actions/workflows/desktop.yml), open a successful run, and download the Windows/macOS/Linux artifacts. GitHub may require login to download Actions artifacts.

## Draft release
`.github/workflows/release-desktop.yml` stages a **draft prerelease** when a successful main-branch packaging run contains all three installer types. The release is not automatically published publicly; review and test the binaries first. A draft release does not mean that the app is production ready.

The installers bundle the Python backend and Rust gateway. llama.cpp and model weights still require setup. The code does not implement continuous GPU training.
