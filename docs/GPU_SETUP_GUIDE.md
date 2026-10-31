# GPU setup and model-selection guide

The experimental desktop installer includes the Python backend, but not the local inference engine, model weights or GPU drivers.

## Hardware check

Run `python scripts/gpu_diagnostics.py` to inspect detected NVIDIA GPU information, Apple Silicon support indicators and installed tools. It does not benchmark VRAM or install drivers. AMD ROCm compatibility requires further verification.

## Model selection

Choose a reputable code-capable GGUF model with appropriate licensing. For lower-VRAM systems, start with a smaller Q4-quantized model and a 2048–4096 context window. Models still require finite RAM/VRAM, and GPU offloading may fail on unsupported hardware. For CPU-only mode, use `--gpu-layers 0`.

## Local model setup

Install llama.cpp from its official repository and Rust/Cargo. Download a model separately, then run `python scripts/local_stack.py --model /path/to/model-Q4_K_M.gguf` from the source checkout. The standalone desktop installer does not yet include these dependencies or manage their lifecycle.

## Distribution status

Packaging jobs are configured for Windows, macOS and Linux, but a successful workflow run does not establish that installers are signed, notarized, GPU-compatible or safe for broad distribution. Test each installer on a clean machine before release.

## Supervised desktop model lifecycle (October 2026)

The Electron setup runs the selected `llama-server` on the **downloader's computer**, bound to `127.0.0.1:9931`. The packaged Rust gateway remains bound to `127.0.0.1:8088`. These are fixed ports for the experimental release. Startup rejects occupied ports rather than trusting an unidentified pre-existing service. Simultaneous startup attempts are rejected.

The selected llama.cpp executable is probed for accelerator backends. Auto mode attempts GPU offload and retries with `-ngl 0` if startup fails; manual mode never silently falls back. Successful HTTP readiness is not proof of GPU usage. Only a recognized llama.cpp log line showing a nonzero number of layers offloaded to GPU counts as **confirmed** offload; otherwise GPU offload is explicitly **unverified**. Engine/device/driver compatibility and actual token generation still require clean-machine testing.

Unit tests simulate GPU startup failure, fallback, CPU-only hardware, occupied ports, and local process shutdown. The desktop does **not** package a GPU driver, llama.cpp binary, or model weights; source and binaries selected by users must be trusted. Do not expose the local services to the network.
