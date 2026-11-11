"""Opt-in offline CUDA/ROCm/MPS LoRA training against user-approved SQLite feedback.

Requires a local Hugging Face-format causal LM (not a GGUF file) and the optional
training dependencies. The resulting adapter is NOT loaded by llama.cpp.
Candidate promotion is guarded by a held-out cross-entropy regression test.
"""
import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

from services.licensing.policy import ModelLicenseError, require_model_use

def split_examples(rows):
    """Stable 20% holdout. Never evaluate on examples used in training."""
    if len(rows) < 12:
        raise ValueError("At least 12 approved examples are required")
    ordered = sorted(rows, key=lambda row: hashlib.sha256(str(row[0]).encode()).hexdigest())
    holdout = max(2, len(ordered) // 5)
    return ordered[holdout:], ordered[:holdout]

def should_promote(baseline_loss, candidate_loss, minimum_fraction=0.01):
    if not all(math.isfinite(x) and x > 0 for x in (baseline_loss, candidate_loss)):
        return False
    return candidate_loss <= baseline_loss * (1 - minimum_fraction)

def manifest_path(root):
    return root / ".agent" / "models" / "active.json"

def read_active(root):
    path = manifest_path(root)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

def activate(root, version, baseline, candidate, base_model, model_id=None, model_license=None):
    """Atomically publish a pointer to an existing candidate adapter directory."""
    root = Path(root)
    adapter = root / ".agent" / "models" / "versions" / version
    if not adapter.is_dir() or not (adapter / "adapter_config.json").is_file():
        raise ValueError("Candidate adapter is missing or incomplete")
    previous = read_active(root)
    record = {"active": version, "previous": previous["active"] if previous else None,
              "baseline_eval_loss": baseline, "candidate_eval_loss": candidate,
              "base_model": str(base_model)}
    if model_id is not None:
        record["model_id"] = str(model_id)
    if model_license is not None:
        record["model_license"] = str(model_license)
    destination = manifest_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, prefix=".active-",
                                     encoding="utf-8", delete=False) as handle:
        temp = Path(handle.name)
        json.dump(record, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, destination)
    return record

def rollback(root):
    root = Path(root)
    previous = read_active(root)
    if not previous or not previous.get("previous"):
        raise ValueError("No earlier candidate adapter is available")
    parent = root / ".agent" / "models" / "versions"
    version = previous["previous"]
    if not (parent / version / "adapter_config.json").is_file():
        raise ValueError("Previous adapter is missing")
    destination = manifest_path(root)
    entry = dict(previous)
    entry["active"] = version
    entry["previous"] = None
    with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, prefix=".rollback-",
                                     encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(entry, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)
    return entry

def read_only_uri(database):
    """Build a SQLite URI that works with drive letters and POSIX paths."""
    return Path(database).resolve().as_uri() + "?mode=ro"

def approved_examples(root, maximum):
    database = root / ".agent" / "feedback.sqlite3"
    if not database.is_file():
        raise ValueError("No opted-in feedback database exists")
    with closing(sqlite3.connect(read_only_uri(database), uri=True)) as conn:
        return conn.execute("SELECT id,prompt,response FROM feedback ORDER BY created_at,id LIMIT ?",
                            (maximum,)).fetchall()

def make_features(tokenizer, rows, max_tokens):
    result = []
    eos = tokenizer.eos_token_id
    if eos is None:
        raise ValueError("Model tokenizer needs an EOS token")
    for _, prompt, response in rows:
        prefix = "### Task\n" + prompt + "\n### Answer\n"
        first = tokenizer(prefix, add_special_tokens=False)["input_ids"]
        second = tokenizer(response, add_special_tokens=False)["input_ids"] + [eos]
        # Keep at least one response token, and never label the prompt as target.
        first = first[:max_tokens // 2]
        second = second[:max_tokens - len(first)]
        if len(second) < 2:
            continue
        result.append((first + second, [-100] * len(first) + second))
    if not result:
        raise ValueError("No usable training examples")
    return result

def select_training_device(torch):
    """Use the downloader's NVIDIA/ROCm CUDA-compatible GPU or Apple MPS device.

    PyTorch exposes supported AMD ROCm builds under torch.cuda. A machine with
    no supported accelerator must opt out; training never silently moves to a
    cloud service or spins on an unexpected CPU.
    """
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    raise RuntimeError("No compatible local GPU detected; install a CUDA/ROCm or Apple MPS PyTorch build")

def feature_tensors(torch, ids, labels, device):
    """Create model inputs on the same accelerator selected for the model."""
    return (torch.tensor([ids], device=device),
            torch.tensor([labels], device=device))

def evaluate(model, features, torch, device):
    model.eval()
    losses = []
    with torch.no_grad():
        for ids, labels in features:
            input_ids, label_ids = feature_tensors(torch, ids, labels, device)
            output = model(input_ids=input_ids, labels=label_ids)
            value = float(output.loss.detach().float().cpu())
            if not math.isfinite(value):
                raise ValueError("Evaluation produced a non-finite loss")
            losses.append(value)
    return sum(losses) / len(losses)

def train(root, base_model, steps, maximum, minimum_gain, targets, max_tokens,
          model_id=None, model_license=None):
    """Train only after the reviewed model license explicitly permits training."""
    if not model_id or not model_license:
        raise ValueError("Reviewed --model-id and --model-license are required before training")
    require_model_use(model_id, model_license, "training")
    # Imports stay inside this function so rollback and split tests need no GPU deps.
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        from peft import LoraConfig, get_peft_model
    except ImportError as exc:
        raise RuntimeError("Install requirements-training.txt first") from exc
    device = select_training_device(torch)
    model_dir = Path(base_model).resolve()
    if not model_dir.is_dir():
        raise ValueError("Pass a downloaded local Hugging Face-format model directory, not GGUF")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    rows = approved_examples(root, maximum)
    learning, holdout = split_examples(rows)
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True,
                                               trust_remote_code=False)
    train_data = make_features(tokenizer, learning, max_tokens)
    test_data = make_features(tokenizer, holdout, max_tokens)
    torch.manual_seed(42)
    model = AutoModelForCausalLM.from_pretrained(str(model_dir), local_files_only=True,
                                                  trust_remote_code=False,
                                                  torch_dtype=torch.float16)
    model.to(device)
    baseline = evaluate(model, test_data, torch, device)
    adapter = get_peft_model(model, LoraConfig(
        task_type="CAUSAL_LM", r=8, lora_alpha=16, lora_dropout=0.05,
        bias="none", target_modules=targets))
    adapter.train()
    optimizer = torch.optim.AdamW((p for p in adapter.parameters() if p.requires_grad),
                                  lr=0.00005)
    for step in range(steps):
        ids, labels = train_data[step % len(train_data)]
        tokens, answers = feature_tensors(torch, ids, labels, device)
        optimizer.zero_grad(set_to_none=True)
        loss = adapter(input_ids=tokens, labels=answers).loss
        if not torch.isfinite(loss):
            raise RuntimeError("Training loss became non-finite")
        loss.backward()
        torch.nn.utils.clip_grad_norm_((p for p in adapter.parameters() if p.requires_grad), 1.0)
        optimizer.step()
    candidate = evaluate(adapter, test_data, torch, device)
    if not should_promote(baseline, candidate, minimum_gain):
        return {"promoted": False, "device": device, "baseline_loss": baseline, "candidate_loss": candidate,
                "examples_trained": len(train_data), "examples_evaluated": len(test_data)}
    version = uuid.uuid4().hex
    versions = root / ".agent" / "models" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=versions, prefix=".adapter-") as temporary:
        adapter.save_pretrained(temporary, safe_serialization=True)
        if not (Path(temporary) / "adapter_config.json").is_file():
            raise RuntimeError("Adapter was not saved correctly")
        os.replace(temporary, versions / version)
    record = activate(root, version, baseline, candidate, model_dir, model_id, model_license)
    return {"promoted": True, "device": device, "version": version, "baseline_loss": baseline,
            "candidate_loss": candidate, "examples_trained": len(train_data),
            "examples_evaluated": len(test_data), "previous": record["previous"],
            "model_id": model_id, "model_license": model_license}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Project folder under WORKSPACE_ROOT")
    parser.add_argument("--model-dir", help="Local Hugging Face-format causal language model")
    parser.add_argument("--model-id", help="Exact reviewed model id, e.g. Qwen/Qwen2.5-Coder-7B-Instruct")
    parser.add_argument("--model-license", help="Exact license id from security/model-policy.json")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--max-examples", type=int, default=250)
    parser.add_argument("--min-gain", type=float, default=0.01)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--target-modules", default="q_proj,v_proj")
    parser.add_argument("--consent-to-gpu-training", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}", args.project):
        parser.error("Invalid project name")
    root = (Path(os.getenv("WORKSPACE_ROOT", "./workspaces")).resolve() / args.project)
    if not root.is_dir():
        parser.error("Project workspace not found")
    if args.rollback:
        print(json.dumps(rollback(root), indent=2))
        return
    if not args.consent_to_gpu_training:
        parser.error("Explicit --consent-to-gpu-training is required")
    if not args.model_id or not args.model_license:
        parser.error("--model-id and --model-license are required so the license gate can run")
    try:
        require_model_use(args.model_id, args.model_license, "training")
    except ModelLicenseError as exc:
        parser.error(f"Model license is not approved for training: {exc}")
    if not args.model_dir or not 1 <= args.steps <= 100 or not 12 <= args.max_examples <= 2000 or not 0 <= args.min_gain <= 0.5 or not 128 <= args.max_tokens <= 2048:
        parser.error("Invalid model path, step count, sample limit, threshold or token budget")
    targets = [x.strip() for x in args.target_modules.split(",") if x.strip()]
    if not targets or len(targets) > 8:
        parser.error("Specify between 1 and 8 LoRA target modules")
    print(json.dumps(train(root, args.model_dir, args.steps, args.max_examples,
                           args.min_gain, targets, args.max_tokens,
                           model_id=args.model_id, model_license=args.model_license), indent=2))

if __name__ == "__main__":
    main()
