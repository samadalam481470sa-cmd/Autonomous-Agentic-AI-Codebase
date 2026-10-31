# Legal reuse of open-source components

This project uses or can integrate existing open-source software **as dependencies**, rather than copying arbitrary GitHub repositories into its source tree.

- llama.cpp (https://github.com/ggml-org/llama.cpp) is a local inference engine under the MIT license. Obtain official source or binaries and preserve its copyright/license notices when redistributing. The desktop app currently requires users to select a compatible llama-server executable.
- Electron (https://github.com/electron/electron) provides the desktop runtime; comply with its MIT license and third-party notices.
- FastAPI, Python libraries and Rust crates are resolved from their package registries; check each dependency license and version before commercial distribution.

Do not copy repositories without checking the exact license, authorship, patents, attribution and dependency notices. Copying tens of thousands of lines from another project does not make this app production-ready.

GitHub Packages hosts a small npm **API client**, not the operating-system installers. Desktop installers are handled by the GitHub Releases workflow. Neither the API client nor the app currently performs self-training on the user's GPU.
