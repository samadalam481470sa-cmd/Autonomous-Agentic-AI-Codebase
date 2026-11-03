# Legally usable open source

`third_party/oss_registry.json` is the single source of truth for every external
project this repository vendors, links, installs or references. It is validated
by `scripts/check_oss_licenses.py`, which runs in CI and in the test suite.

## Policy

- Only permissively licensed code may be **bundled**: MIT, Apache-2.0,
  BSD-2-Clause, BSD-3-Clause, ISC, MPL-2.0, 0BSD or Unlicense.
- Vendored components must keep their copyright notice and license text, and the
  registry must point at that notice file. The checker verifies the file exists
  and contains the expected license text.
- Copyleft projects (GPL/AGPL/LGPL/SSPL/EUPL) must be `bundled: false`, must
  explain how they are isolated, and require independent review before any
  combined distribution.
- Every entry has a documented version or pin. No floating "latest" code.
- Referenced projects that are not yet integrated are labelled `reference` so
  nobody mistakes a design reference for shipped code.

## Registered projects

| Project | License | Use |
| --- | --- | --- |
| [microsoft/monaco-editor](https://github.com/microsoft/monaco-editor) | MIT | Vendored editor source in `third_party/monaco-editor` |
| [microsoft/vscode](https://github.com/microsoft/vscode) | MIT | Pinned Code-OSS workbench submodule |
| [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | MIT | Operator-installed local inference runtime |
| [Fosowl/agenticSeek](https://github.com/Fosowl/agenticSeek) | GPL-3.0-only | Isolated optional submodule and HTTP bridge only |
| [fastapi/fastapi](https://github.com/fastapi/fastapi) | MIT | Runtime dependency |
| [encode/uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | Runtime dependency |
| [encode/httpx](https://github.com/encode/httpx) | BSD-3-Clause | Runtime dependency |
| [pydantic/pydantic](https://github.com/pydantic/pydantic) | MIT | Runtime dependency |
| [pytest-dev/pytest](https://github.com/pytest-dev/pytest) | MIT | Development dependency |
| [electron/electron](https://github.com/electron/electron) | MIT | Desktop packaging |
| [evanw/esbuild](https://github.com/evanw/esbuild) | MIT | Web bundle build |
| [microsoft/agent-framework](https://github.com/microsoft/agent-framework) | MIT | Architecture reference |
| [tree-sitter/tree-sitter](https://github.com/tree-sitter/tree-sitter) | MIT | Parser reference (not integrated) |
| [huggingface/tokenizers](https://github.com/huggingface/tokenizers) | Apache-2.0 | Tokenisation reference (not integrated) |
| [UKPLab/sentence-transformers](https://github.com/UKPLab/sentence-transformers) | Apache-2.0 | Optional future embedding backend (not integrated) |
| [facebookresearch/faiss](https://github.com/facebookresearch/faiss) | MIT | ANN reference (not integrated) |
| [openai/tiktoken](https://github.com/openai/tiktoken) | MIT | Token-budget reference (not integrated) |

The retrieval engine in `services/api/semantic.py` is original code; it does not
copy from any registered reference project.

## Adding a dependency

1. Confirm the SPDX license is on the allowlist (or that the project is clearly
   isolated and not bundled).
2. Append an entry with `name`, `repo`, `license`, `usage`, `pin`, `bundled` and
   `notice` (for vendored code) or `isolation` (for copyleft code).
3. If vendored, copy the upstream `LICENSE` and `ThirdPartyNotices` into
   `third_party/<name>/` and preserve the original copyright lines.
4. Run `python scripts/check_oss_licenses.py` and `pytest -q`.

## Attribution

The Monaco Editor copyright, MIT license and third-party notices are preserved
in `third_party/monaco-editor`. Do not present vendored upstream lines as
first-party work. For any distribution, include the registry, the preserved
notices and this document; the checker fails the build if a notice goes missing.

## Not legal advice

This registry records provenance and enforces a conservative policy. It is not a
legal opinion. Review obligations for your distribution model with counsel,
especially for the optional GPL-3.0 AgenticSeek integration.
