# Uploaded source references and provenance

This repository records two artifacts supplied for the local-first IDE project on 2026-10-31. Both are **source references**, not completed production IDE features.

## AgenticSeek archive

- Uploaded file: `agenticSeek(1).zip`; SHA-256: `ded56f521b462e7e0712b8da982407fa6ba3c96d6d9da2133b288534158abbf1`.
- ZIP size: **10,185,088 bytes**, 211 entries, total uncompressed size **12,571,259 bytes**.
- All ZIP paths are under `agenticSeek/`; no absolute or parent-directory ZIP entry names were found in the static inspection.
- Contains an AgenticSeek `LICENSE` stating GNU GPL v3, executable scripts, Python/browser automation and a third-party `.crx` binary. Presence in the archive is not a security clearance.
- No obvious plaintext credential signatures matched the limited static check, **not** proof that it is safe. No binaries or dependencies have been executed.

The original ZIP is **not** copied into this Git repository. Instead `upstream/agenticseek` is a Git submodule referencing the project's independent GPL-3.0 upstream at pinned commit `4f5f924c1eb326b4163d3bf942954dcc7dd7875b`. This is a **separate reference snapshot** selected from the upstream Git repository. Its contents have **not** been proven byte-identical to the uploaded ZIP. Do not claim that a submodule is the uploaded archive, or that any AgenticSeek server is shipped in our IDE.

To explicitly inspect sources locally:

```bash
git submodule update --init upstream/agenticseek
git -C upstream/agenticseek rev-parse HEAD
```

Do not install or execute it just by checking out the Code-OSS IDE. GPL-3.0 distribution obligations, dependency risks, and isolated execution need a separate review. This repository's opt-in authenticated HTTP bridge remains separate from the source and is not automatically enabled. See [AgenticSeek integration](AGENTICSEEK_INTEGRATION.md) and [static upload scan](../security/UPLOAD_SCAN.md).

## Forge Dashboard README

- Uploaded file: `README(2).md`; SHA-256: `6e00c5b464592fbf64f9ec8e28fa1a8e82ac5998ac2756c12dd0f4580cd0cdaa`.
- Full user-supplied design README committed to [`docs/forge-dashboard/README.md`](forge-dashboard/README.md).
- Describes **28 screens**, React/TypeScript/Vite front end, a separate Rust sidecar on `127.0.0.1:7420`, and mock data mode.

Only the README was provided: **no Forge Dashboard `src/` tree, Node package, Rust sidecar, or automated screenshot artifacts came in this upload**. Descriptions of functionality and test coverage in the design README are not verified implementation claims for this repository. The 28 screens are not added to the executable IDE by this commit.

## Integration and release boundary

The Code-OSS app remains the editor. The Forge Dashboard is a reference design. AgenticSeek is an optional third-party source submodule and separately run service. Neither reference is bundled in the experimental Code-OSS Linux release; no local GPU, browser automation or enterprise account-management claim follows from adding these references.
