# Local AI startup — one command

This launcher starts **three existing local components**: llama.cpp, the Rust inference gateway and the Python coding backend. It performs readiness checks and terminates children on Ctrl+C. It **does not** automatically install llama.cpp, Rust, Python dependencies, GPU drivers or model weights.

## Prerequisites

1. Install Python 3.11+, Rust/Cargo and a compatible llama.cpp `llama-server` binary.
2. Download a code-capable GGUF model that you have permission to use; prefer Q4 quantization if VRAM is limited.
3. Install the Python dependencies from the repository requirements file.
4. Ensure ports 9931, 8088 and 8000 are free. Keep these ports on loopback only.

## Launch

From the repository root:

```bash
python scripts/local_stack.py --model /absolute/path/to/coder-Q4_K_M.gguf --gpu-layers 99 --context 4096
```

Windows PowerShell:

```powershell
py scripts/local_stack.py --model "C:/Models/coder-Q4_K_M.gguf" --gpu-layers 99 --context 4096
```

Use `--gpu-layers 0` to force CPU inference, or reduce the number if the model doesn't fit in VRAM. The script prints a temporary admin token for the Studio UI. It is not persisted; keep it private.

On Windows PowerShell, use a native path and Python launcher, for example `py scripts/local_stack.py --model "C:/Models/coder-Q4_K_M.gguf" --gpu-layers 99 --context 4096`. Ctrl+C stops the whole child process tree on both Windows and POSIX.

Open `http://127.0.0.1:8000/studio`. You can optionally run the Electron desktop client separately.

```bash
python scripts/local_stack.py --model /path/to/model.gguf --dry-run
```

The dry-run checks paths and executables only; it does not test model compatibility or GPU availability.

## Limitations

- This is a **developer launcher**, not a signed, self-installing consumer desktop app.
- The launcher does not currently package the backend with Electron.
- Inference quality, tool calling, performance and GPU utilization vary by model, template and hardware.
- Rust's gateway has concurrency and output limits; finite context remains.
- Do not expose the local model services or their unauthenticated ports to external networks.
- Model files can be untrusted: download from reputable sources, verify checksums when supplied and review licenses.
