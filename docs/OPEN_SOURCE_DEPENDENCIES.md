# Legal reuse of open-source components

This project uses or can integrate existing open-source software **as reviewed dependencies**, rather than copying arbitrary repositories into its source tree.

- llama.cpp (https://github.com/ggml-org/llama.cpp) is a local inference engine under the MIT license. Obtain official source or binaries and preserve its copyright/license notices when redistributing. The desktop app currently requires users to select a compatible llama-server executable.
- Electron (https://github.com/electron/electron) provides the desktop runtime; comply with its MIT license and third-party notices.
- FastAPI, Python libraries, Node packages, and Rust crates are resolved from their package registries. Their licenses are checked by `python scripts/license_scan.py` against [`security/license-policy.json`](../security/license-policy.json).
- Model weights are reviewed separately in [`security/model-policy.json`](../security/model-policy.json); they are not software dependencies and custom community licenses are not approved by license name alone.

The policy is an allowlist. GPL, AGPL, LGPL, SSPL, BUSL, non-commercial, JSON, and unknown licenses fail the build unless a narrow, written exception exists. CI runs the full dependency, model, and provenance scan in [`.github/workflows/license-compliance.yml`](../.github/workflows/license-compliance.yml).

Do not copy repositories without checking the exact license, authorship, patents, attribution and dependency notices. Copying tens of thousands of lines from another project does not make this app production-ready.

GitHub Packages hosts a small npm **API client**, not the operating-system installers. Desktop installers are handled by the GitHub Releases workflow. Neither the API client nor the app currently performs self-training on the user's GPU.

See [license and provenance governance](LICENSING.md) for commands, exception rules, model obligations, and the AgenticSeek boundary.
