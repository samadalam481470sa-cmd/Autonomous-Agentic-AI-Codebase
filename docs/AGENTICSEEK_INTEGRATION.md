# AgenticSeek integration — security and licensing

The user-supplied `agenticSeek.zip` was inspected **statically** before integration. It contains 211 archive entries (~12.6 MB uncompressed) and a GPL-3.0 license. It includes browser automation, shell interpreters, browser stealth tooling, network calls, installation scripts and a bundled browser extension (`crx/nopecha.crx`). These are sensitive capabilities, not proof of malware.

**No claim of malware-free status:** Static keyword inspection and archive path checks cannot establish that source, dependencies, extensions, downloads or runtime behavior are safe. We did not execute the uploaded archive, install its dependencies, or import its code into this repository.

## Design decision

AgenticSeek is GPL-3.0; Microsoft's Agent Framework is MIT-licensed. To avoid silently relicensing the entire repository or copying code without preserving obligations, this repository **does not vendor or modify AgenticSeek**. Instead it contains an original, optional HTTP adapter calling AgenticSeek's documented `POST /query` API with `{query, tts_enabled:false}`. The adapter reads the answer, status, and agent name. This is a separate-process integration, not a guarantee about whether any particular deployment's distribution arrangement triggers GPL obligations; consult counsel if distributing a combined product.

## Setup

1. Independently inspect the upstream source and license at https://github.com/Fosowl/agenticSeek.
2. Install and run AgenticSeek in a **separate, locked-down VM/container**, with no personal browser profile, no host secrets or sensitive files, restricted network and filesystem access, and an explicit API token.
3. Bind its API only to loopback. For containers, use an explicit loopback forwarding tunnel; do not publish the agent service to the internet.
4. Configure `AGENTICSEEK_URL=http://127.0.0.1:8001` and `AGENTICSEEK_API_TOKEN=<your-secret>` on this app.
5. Invoke `POST /api/integrations/agenticseek/query` with `{project, message}` only on a **trusted, local** deployment. The adapter is opt-in and disabled when unconfigured.

**Warning:** The integration endpoint is not yet authenticated. Do not expose this app to other users or networks. Delegated actions may cause side effects; this MVP has no per-action approval UI.

## Static scan observations

- Archive traversal entries: none detected.
- GPL-3.0 LICENSE present.
- Contains command execution and browser automation features, including `subprocess`, `os.system`, and Selenium.
- Bundled `.crx` binary and installer/download scripts warrant separate inspection.
- No malware verdict is possible without deeper provenance, dependency, dynamic and binary analysis.

## Future work

Add authenticated access, human approvals, sandbox isolation, malware scanning (e.g. ClamAV and YARA), SBOM and dependency advisories, signed artifact provenance, and independent security testing before allowing arbitrary user-supplied agents.
