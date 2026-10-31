# Rust performance module

This release adds a standalone Rust workspace indexer at `services/runtime-rust`. It enumerates up to 10,000 project files, skips common generated directories and symbolic links, and emits JSON metadata for downstream code search/indexing.

```bash
cd services/runtime-rust
cargo test
cargo run --release -- scan ../../workspaces/demo
```

**Why Rust?** Efficient file traversal, predictable memory usage, low overhead, and future potential for high-performance code indexing and model-serving integration. The current Rust component does **not** run the language model, replace Python inference orchestration, or lower GPU VRAM consumption.

To reduce GPU memory use, use a quantized local model, smaller context windows, and an inference runtime with compatible GPU acceleration. Quantization and CPU offloading can reduce VRAM at the cost of potential quality and speed trade-offs. `llama.cpp` is a possible future inference backend; its core is C/C++, and a Rust wrapper would not by itself change model memory needs.

The Rust scanner is intentionally not exposed as an unauthenticated API or arbitrary host command executor.
