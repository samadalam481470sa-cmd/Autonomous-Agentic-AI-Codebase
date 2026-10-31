# Rust + llama.cpp local inference

This implements a **Rust inference gateway**, not a Rust rewrite of the model itself. llama.cpp performs quantized CPU/GPU inference; the Rust service bounds concurrent requests and output tokens and connects it to the Python agent.

## 1. Install llama.cpp and obtain a GGUF model

Follow the upstream documentation: https://github.com/ggml-org/llama.cpp/tree/master/tools/server

Choose a legally usable GGUF coding model that fits your available memory, ideally a Q4 quantization. The model weights are not distributed by this repository.

For an already downloaded model:

```bash
llama-server -m /absolute/path/to/coder-Q4_K_M.gguf --host 127.0.0.1 --port 9931 -c 4096 -ngl 99 --jinja
```

`-ngl 99` requests GPU offload when supported. Adjust it downward if VRAM is insufficient, or set `-ngl 0` for CPU-only inference. `--jinja` supports tool-call templates on compatible models; actual function calling depends on the chosen model/template.

## 2. Run the Rust gateway

```bash
cd services/runtime-rust
cargo run --release -- serve
```

By default it listens at `127.0.0.1:8088` and forwards to `127.0.0.1:9931/v1`. Configurable variables: `LLAMA_UPSTREAM`, `RUST_GATEWAY_PORT`, `RUST_MAX_OUTPUT_TOKENS` (64–8192), and `RUST_MAX_CONCURRENT` (1–4). Requests are capped at 256 KB and 40 messages. The gateway supports both standard JSON responses and opt-in OpenAI-compatible Server-Sent Events (SSE) via `stream: true`. The concurrency slot remains held for the entire stream and is released when it finishes or the client disconnects. This is local gateway streaming support; it is not proof of GPU acceleration, a browser-streaming interface, or agent tool-event streaming.

## 3. Connect Python

```bash
export LOCAL_MODEL_ONLY=1
export LOCAL_MODEL_BASE_URL=http://127.0.0.1:8088/v1
export LOCAL_MODEL_NAME=local-model
export LOCAL_CONTEXT_CHAR_BUDGET=12000
export LOCAL_MAX_OUTPUT_TOKENS=1024
export AGENT_ADMIN_TOKEN=use-a-strong-random-token
uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

The model's actual name can be inspected via `http://127.0.0.1:8088/v1/models`. Replace `local-model` if the server requires a specific name.

## Limits and safety

Rust improves service efficiency and throughput control, but does not inherently reduce model VRAM. The primary VRAM savings come from Q4 model quantization, smaller context windows, and partial GPU offload. Context budgeting here uses a **character-based heuristic**, not exact token counting. No automatic model installation, GPU driver management, model benchmarks, or Windows desktop backend bundling is included.

All three services run on the **user's computer**, not a remote inference data center, when local-only mode is enabled. Keep them bound to loopback; the Rust gateway does not provide authentication and must not be exposed to a network.

## 4. Browser live chat

With `LOCAL_MODEL_ONLY=1`, open the main chat page and enable **Stream local chat**. The FastAPI `/api/chat/stream` bridge authenticates the user, reads recent project history, and sends an OpenAI-compatible `stream: true` request only to the configured loopback Rust gateway. It emits JSON-encoded `delta`, `done`, and `error` SSE events. It only persists finished nonempty answers; disconnected or invalid responses are not recorded. Output and token counts are bounded.

This opt-in path is **text chat only** and intentionally uses `tool_choice: none`. The existing non-streamed `/api/chat` is still the agent/tool-enabled workflow. Future work includes streamed tool events, cancellation, checkpoint integration and actual on-device GPU inference benchmarks.
