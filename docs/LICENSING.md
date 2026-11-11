# License and provenance governance

This repository ships application code, a vendored MIT editor snapshot, two upstream Git submodules, and optional local model weights. Those are four different provenance classes. The project treats each separately and **fails closed** when a dependency, model, or upstream tree has not been reviewed.

This document describes engineering controls, not legal advice. Distributing a combined product may create obligations that require counsel.

## 1. First-party code

The application, CLI scripts, tests, Python API, Rust gateway, desktop shell, web UI, `packages/ui`, and `packages/client` are first-party work licensed under the repository [MIT license](../LICENSE). The Axiom token palette, scales, and 43 icon geometries are original and self-contained; no third-party icon assets are copied. See [design-system provenance](../packages/ui/PROVENANCE.md). Generated files (`apps/web/assets/`, `packages/ui/dist/`) are build output and are never counted as authored source.

## 2. Dependency licenses

The policy is [`security/license-policy.json`](../security/license-policy.json). A dependency passes only when every applicable license in its SPDX expression appears in `allowed_licenses`, or a package-specific exception names the package, version, license, and reason.

- Blocked by default: GPL, AGPL, LGPL, SSPL, BUSL, non-commercial Creative Commons, JSON, and unknown licenses.
- MPL-2.0, OpenSSL, Unicode data, and CDLA-Permissive-2.0 licenses are **conditional**: they pass only while the dependency or data file remains unmodified and its notices are preserved. CDLA-Permissive-2.0 is approved only for the certificate-root data in `webpki-roots`, not for executable code.
- Exceptions are narrow and auditable. The only current exception is PyInstaller, a build-time tool whose bootloader exception permits distributing the bundled application under MIT.
- Optional training dependencies are declared and reviewed even though they are not installed in the normal CI environment.

### Run the scan

```bash
python scripts/license_scan.py \
  --python --requirements --vendored --models \
  --node apps/web --node apps/desktop --node apps/vscode-extension \
  --cargo services/runtime-rust/Cargo.toml \
  --report security/reports/license-report.json
```

The scanner covers installed Python distributions (including metadata classifiers), declared Python requirements, installed Node packages, resolved Rust crates through `cargo metadata`, vendored trees, the first-party license, the model registry, and the bundled-model manifest.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Every scanned record is approved or explicitly conditional |
| `1` | At least one blocked/unknown license, unreviewed dependency, or unshippable model |
| `2` | A scan could not be completed (for example, Node dependencies were not installed) |

CI runs the full scan in [`license-compliance.yml`](../.github/workflows/license-compliance.yml), uploads the JSON report, and blocks the workflow on any violation. [`ci.yml`](../.github/workflows/ci.yml) also runs the offline portions on every push and pull request.

### Adding or upgrading a dependency

1. Read the exact declared license at the installed version, not the project README.
2. Check transitive dependencies; an MIT wrapper around a GPL binary is still blocked.
3. If the license is already allowed, no policy edit is needed; CI will still verify it.
4. If it is a new license or needs an exception, update `allowed_licenses`, `conditional_licenses`, or `exceptions` with a written reason. Do not add a blanket `*` exception.
5. For a new declared Python requirement, add it to `declared_dependencies.python`.
6. Re-run the scan and commit the updated policy. The scan report itself is generated and ignored.

Proprietary build tools are not automatically acceptable. The VS Code extension intentionally has no `@vscode/vsce` development dependency because its signing packages carry a Microsoft EULA that restricts redistribution. Extension packaging is external and must use an independently reviewed tool. Do not evade the scan by invoking a package through `npx` or an unlisted download.

## 3. Model licenses

Model weights are **not software dependencies**. Several capable coding models use custom community licenses that are not OSI-approved. The reviewed registry is [`security/model-policy.json`](../security/model-policy.json); every use is tracked separately:

| Use | Meaning |
| --- | --- |
| `inference` | Run the model locally or through a compatible endpoint |
| `training` | Fine-tune or train on the model |
| `redistribution` | Provide the weights to a third party |
| `shipping` | Bundle weights inside a release artifact |

Current reviewed models:

| Model | License | Inference | Training | Redistribution | Shipping |
| --- | --- | --- | --- | --- | --- |
| `Qwen/Qwen2.5-Coder-7B-Instruct` | Apache-2.0 | Yes | Yes | Yes | Yes |
| `mistralai/Mistral-7B-Instruct-v0.3` | Apache-2.0 | Yes | Yes | Yes | Yes |
| `meta-llama/Llama-3.1-8B-Instruct` | Llama 3.1 Community | Yes | Yes | Yes, with obligations | **No** |
| `google/gemma-2-9b-it` | Gemma Terms of Use | Yes | Yes | Yes, with obligations | **No** |

The registry records the source URL, review date, commercial-use answer, obligations, and notes. Llama requires the agreement, notice file, "Built with Llama", a `Llama` prefix on distributed derivatives, and a separate Meta license above 700 million monthly active users. Gemma requires pass-through of its use restrictions, agreement/notice delivery, modification marking, and compliance with the Gemma Prohibited Use Policy. The project does not bundle either set of weights.

### Check a model

```bash
python scripts/check_model_license.py --list
python scripts/check_model_license.py --validate
python scripts/check_model_license.py \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --license Apache-2.0 --use training
python scripts/check_model_license.py --manifest security/model-distribution.json
```

Unknown models, mismatched license strings, unknown uses, and unreviewed custom licenses are denied. `--manifest` checks every model declared as bundled in [`security/model-distribution.json`](../security/model-distribution.json) for the `shipping` permission. The manifest is currently empty because release artifacts do not contain weights.

### Training gate

[`scripts/local_lora_training.py`](../scripts/local_lora_training.py) refuses to import PyTorch or load a model unless both `--model-id` and `--model-license` match the reviewed registry **and** the model has `uses.training: true`. The activated adapter manifest records the model id and reviewed license.

```bash
python scripts/local_lora_training.py \
  --project demo \
  --model-dir /models/Qwen2.5-Coder-7B-Instruct \
  --model-id Qwen/Qwen2.5-Coder-7B-Instruct \
  --model-license Apache-2.0 \
  --consent-to-gpu-training
```

### Desktop download gate

The Electron setup screen asks for the reviewed model id and exact license id. The main process checks the shared registry **before** opening a network connection, and the download IPC handler checks it again. A SHA256 checksum and explicit license acknowledgement are still required. The policy file is packaged as an Electron resource.

### Adding a model

1. Read the provider's canonical license text at the exact model revision.
2. Record the license name, source URL, review date, commercial-use answer, and one boolean per use.
3. For a custom license, add it to `custom_licenses` with `reviewed: true` and explicit obligations.
4. Add model-specific requirements and notes. Deny `shipping` unless the project actually intends to redistribute weights.
5. Add the model to the registry and run `--validate`. A new model cannot pass by name alone.

## 4. Upstream and optional GPL code

| Path | License | Relationship |
| --- | --- | --- |
| `third_party/monaco-editor` | MIT | Vendored source snapshot, notices preserved, built from the pinned npm release |
| `upstream/code-oss` | MIT | Pinned Git submodule, built independently, not a fork |
| `upstream/agenticseek` | GPL-3.0 | Pinned Git submodule, optional, separately operated process only |

AgenticSeek is **never imported, linked, vendored into first-party paths, packaged, or executed** by this application. [`services/api/agenticseek.py`](../services/api/agenticseek.py) provides an authenticated, loopback-only HTTP adapter. The upstream tree stays outside the build and release artifacts.

[`scripts/check_provenance.py`](../scripts/check_provenance.py) fails CI when:

- either required submodule is missing or points at an unexpected URL;
- first-party code references `upstream/agenticseek` or imports external `agenticseek`;
- a build/packaging file includes an upstream tree;
- the adapter gains subprocess/exec/path-injection code or loses its loopback/token markers;
- the first-party license is not MIT;
- an undeclared `third_party/` directory appears;
- AgenticSeek is not recorded as GPL-3.0 and separately operated in the policy.

## 5. What still requires human review

Automated scanning cannot decide whether a license is acceptable for a particular business, whether a model's acceptable-use policy fits a deployment, whether an upstream archive is malware-free, or whether a combined distribution triggers copyleft obligations. Review new licenses, model terms, and distribution plans with counsel when the answer matters.
