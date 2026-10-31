# Offline Monaco editor

Autonomous Agentic AI now integrates the **MIT-licensed Microsoft Monaco Editor** for syntax highlighting, code editing, multi-language support, and local worker-based language services.

- The app builds browser and language-worker bundles at packaging time from pinned `monaco-editor@0.57.0`, using esbuild.
- The generated assets are shipped inside the frozen Python backend and served from the local FastAPI /assets endpoint. There are no CDN requests for the editor.
- The original editor `textarea` stays as a fallback if the Monaco bundle cannot load.
- `third_party/monaco-editor/` contains a pinned upstream source snapshot and license notices. **Those lines are third-party code, not code authored by this project.** The runtime bundle is built from the matching npm release.
- Source-code line metrics distinguish authored implementation from third-party libraries. 50,000 total repository lines is not an indicator of correctness, million-line editing capability or production readiness.

Upstream: https://github.com/microsoft/monaco-editor/tree/v0.57.0
MIT license: https://github.com/microsoft/monaco-editor/blob/v0.57.0/LICENSE.txt

No personal files are sent to Microsoft by the embedded editor.
