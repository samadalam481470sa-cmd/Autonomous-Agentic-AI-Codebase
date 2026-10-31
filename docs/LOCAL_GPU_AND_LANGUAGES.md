# Local GPU inference and language support

## Local model — Ollama example

Install Ollama independently from https://ollama.com/ and choose an appropriate code-capable model. Downloading model weights is a user-initiated action and may require substantial disk space.

```bash
ollama pull qwen2.5-coder:7b
ollama serve
```

Configure the backend:

```bash
export LOCAL_MODEL_ONLY=1
export LOCAL_MODEL_BASE_URL=http://127.0.0.1:11434/v1
export LOCAL_MODEL_NAME=qwen2.5-coder:7b
export AGENT_ADMIN_TOKEN=choose-a-long-random-secret
uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

Ollama chooses available GPU acceleration based on compatible hardware, drivers and model size. Local inference does **not** guarantee GPU use. Some models run on CPU, some spill between CPU/GPU, and unsupported GPUs may not accelerate. Check Ollama logs and GPU monitoring tools to verify.

Local inference avoids paying a remote model API per token, but it does **not** provide unlimited context, unlimited tokens, or unlimited compute. Each model has a finite context window, output limit, memory footprint, and throughput. The agent loop is currently limited to eight tool rounds and history to thirty messages. Longer projects need retrieval, compaction, checkpoints and bounded queues.

## Coding languages

The editor can create and modify UTF-8 files for arbitrary programming languages. The `GET /api/languages` endpoint advertises common extensions for 50+ language families. Syntax highlighting, language servers, debugging and compiling are **not** implemented for every language. Execution is limited to explicitly approved commands in the isolated execution service. Database projects can be generated as SQL migrations and source files for PostgreSQL, MySQL, SQLite, MongoDB clients and others, but live database provisioning and schema execution are not automatic.

## Safety

Local model endpoints are restricted to loopback to reduce SSRF and accidental remote routing. Do not publish Ollama unauthenticated to the internet. Do not give an agent host shell or Docker daemon access. All AI-proposed file changes must pass the Studio approval workflow.
