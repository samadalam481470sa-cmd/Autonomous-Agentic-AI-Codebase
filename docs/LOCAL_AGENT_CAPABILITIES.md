# Experimental local autonomous coding workflow

This application has **bounded multi-file proposal** and **offline Docker trial** APIs, not an unsupervised production coding agent.

## Local setup

1. Install Docker and a compatible local llama.cpp inference server plus a GGUF model. In the desktop app, set up the model and ensure `LOCAL_MODEL_ONLY=1`.
2. Configure `ENABLE_ISOLATED_EXECUTION=1` on the backend only if you trust the local deployment and have Docker configured securely.
3. In Studio, use **AI multi-file** to generate a patch for up to eight explicitly selected files, and **Approve batch** to apply after reading the diffs.
4. Use **AI test & retry** to ask a model to modify a disposable workspace and attempt `python -m compileall -q .` up to three times. The trial runs in Docker with no network, limited memory and CPU, non-root user, read-only bind mount and no privileged capabilities. Nothing is applied to live project files without separate approval. Docker is not guaranteed to isolate a malicious workload from container escapes; use a dedicated VM for untrusted code.

## Voice

Set `WHISPER_LOCAL_URL=http://127.0.0.1:8089` and run a compatible whisper.cpp server exposing `POST /inference`. The chat microphone button records up to eight seconds of WAV data and sends it to the authenticated backend, which forwards it only to loopback. Microphone access requires OS/Electron approval. No speech-to-text model is shipped. Speech synthesis is not integrated.

## Web browsing and privacy

The chat **Browse with AgenticSeek** button uses the existing optional local AgenticSeek adapter. It requires a separately installed compatible AgenticSeek service and `AGENTICSEEK_URL` and `AGENTICSEEK_API_TOKEN`. AgenticSeek's upstream repository currently displays the GPL-3.0 license; it is not copied into this project. Review that license before distributing combined works.

Browser visits, searches, web forms, and external downloads necessarily communicate with websites, so calling this feature **zero data sharing** would be inaccurate. The packaged desktop defaults to local model inference, but the server can also be configured for remote model providers.

## Local feedback and evaluation

`POST /api/learning/feedback` stores an example in a per-project local SQLite database **only** when `consent=true`. The `POST /api/learning/evaluation` endpoint records a candidate-versus-baseline test result and rejects score regressions. These are evaluation records, not proof that a model learned. No GPU training, automatic model promotion, or model-weight rollback is implemented yet.

## Remaining engineering gates

- Clean-install smoke tests on Windows, macOS and Linux, code signing, and dependency/security audits
- Cross-platform whisper.cpp / llama.cpp setup and hardware acceleration selection
- Large-repository benchmarking with measured CPU, RAM, disk and retrieval quality; the generated million-line sample alone does not verify capability
- Syntax-aware dependency graph, incremental reindex deletion and watchers, semantic/hybrid retrieval
- Durable task queue, concurrency isolation, better multi-file atomicity and crash recovery
- Genuine local GPU fine-tuning with isolated opt-in datasets, evaluation against fixed held-out benchmarks, model artifacts, versioning and rollback

GitHub Releases contains experimental draft installers. Publishing a draft or passing CI is not the same as production readiness.
