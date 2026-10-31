# Repository code-size policy

The **50,000+ source-line requirement** is measured objectively using `python scripts/code_metrics.py`.

First-party code and MIT-licensed third-party dependencies are reported **separately**. The source snapshot under `third_party/monaco-editor` is Microsoft's Monaco Editor (v0.57.0), fetched from pinned commit `d61824269f1377111d34306e4a47172327777083` and preserved with its MIT license and third-party notices. It is a legitimate code-editor component, not filler generated to inflate line counts.

The app uses the corresponding npm Monaco version to create a local, offline browser bundle. This provides syntax highlighting, language workers and IDE-like editing, but **it does not mean this project authored all of Monaco's code**. A 50,000-line source snapshot is not evidence that the autonomous model can handle a 50,000-line or million-line project.

The source snapshot is committed automatically by `.github/workflows/vendor-monaco.yml` after verifying the pinned upstream commit, license files and at least 50,000 actual lines of source. Until that job succeeds and its commit appears in `main`, the 50,000-line target has **not** been verified.

Run `python -m scripts.benchmark_million_line_index` to measure the separate million-line repository indexing goal. The benchmark only tests SQLite lexical indexing.
