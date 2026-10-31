# Code size and model learning: accurate measurement

Run `python scripts/code_metrics.py` from a Git checkout to count tracked authored source files and lines. This excludes dependency directories and generated build outputs. **100,000 lines is not a production-readiness standard**; maintainability, coverage, threat modeling and performance matter more.

Local inference with llama.cpp and a Rust gateway does **not** update model weights. A safe future GPU fine-tuning system requires:
1. Explicit user opt-in and clear consent for training on code and feedback.
2. A privacy-preserving local feedback store with secret scanning and data retention controls.
3. A compatible GPU training backend (e.g., LoRA/QLoRA) and separately managed training weights.
4. A held-out evaluation suite with functional, security and regression tests.
5. A model registry with versioned artifacts, approval gates and rollback.
6. GPU utilization limits, pause/resume, temperature monitoring, and clear user controls.

The current project does not implement continual GPU training. Do not market it as self-improving or as an autonomous code-changing system until these pieces are implemented and tested.
