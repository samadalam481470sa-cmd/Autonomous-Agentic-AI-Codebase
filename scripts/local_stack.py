"""Launch local llama.cpp, Rust gateway and Python API from one command.

Does not download binaries/models, elevate privileges, or open firewall ports.
Requires trusted local installations. Ctrl+C stops child processes it started.
"""
import argparse
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def executable(name):
    path=Path(name).expanduser()
    if path.is_file():return str(path.resolve())
    found=shutil.which(name)
    if found:return found
    raise RuntimeError(f"Missing executable: {name}. Install it and add it to PATH.")

def process_group_options():
    """Start each service in a group so its whole tree can be stopped."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}

def terminate_tree(proc, force=False):
    """Stop a child and descendants without touching unrelated processes."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        command = ["taskkill", "/PID", str(proc.pid), "/T"]
        if force:
            command.append("/F")
        try:
            result = subprocess.run(command, check=False, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=10)
            if result.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL if force else signal.SIGTERM)
            return
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.kill() if force else proc.terminate()
    except OSError:
        pass

def wait(url,proc,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if proc.poll() is not None:raise RuntimeError(f"Service exited early with code {proc.returncode}: {url}")
        try:
            with urllib.request.urlopen(url,timeout=1) as response:
                if response.status==200:return
        except (urllib.error.URLError,TimeoutError,OSError):
            pass
        time.sleep(.5)
    raise RuntimeError(f"Service not ready after {timeout}s: {url}")

def config(args):
    model=Path(args.model).expanduser().resolve()
    if not model.is_file() or model.suffix.lower()!=".gguf":
        raise RuntimeError("Select an existing local .gguf model file with --model")
    if args.context<512 or args.context>131072:raise RuntimeError("Context must be 512–131072")
    if args.gpu_layers<0 or args.gpu_layers>999:raise RuntimeError("GPU layers must be 0–999")
    return model

def command_set(args,model):
    llama=executable(args.llama_server)
    cargo=executable("cargo")
    python=sys.executable
    return [
        ("llama.cpp",[llama,"-m",str(model),"--host","127.0.0.1","--port","9931","-c",str(args.context),"-ngl",str(args.gpu_layers),"--jinja"],ROOT),
        ("Rust gateway",[cargo,"run","--release","--","serve"],ROOT/"services"/"runtime-rust"),
        ("Python API",[python,"-m","uvicorn","services.api.main:app","--host","127.0.0.1","--port","8000"],ROOT),
    ]

def main(argv=None):
    parser=argparse.ArgumentParser(description="Start the local AI development stack")
    parser.add_argument("--model",required=True,help="Path to a local GGUF coding model")
    parser.add_argument("--llama-server",default="llama-server")
    parser.add_argument("--context",type=int,default=4096)
    parser.add_argument("--gpu-layers",type=int,default=99)
    parser.add_argument("--token",help="Admin token; omit to generate a temporary one")
    parser.add_argument("--dry-run",action="store_true",help="Check configuration without starting services")
    args=parser.parse_args(argv)
    processes=[]
    try:
        model=config(args)
        commands=command_set(args,model)
        if args.dry_run:
            print("Configuration OK. Found GGUF, llama-server, cargo and Python.")
            return 0
        env=os.environ.copy()
        env.update({
            "LOCAL_MODEL_ONLY":"1",
            "LOCAL_MODEL_BASE_URL":"http://127.0.0.1:8088/v1",
            "LOCAL_MODEL_NAME":env.get("LOCAL_MODEL_NAME",model.stem),
            "LOCAL_CONTEXT_CHAR_BUDGET":str(min(args.context*3,12000)),
            "LOCAL_MAX_OUTPUT_TOKENS":"1024",
            "LLAMA_UPSTREAM":"http://127.0.0.1:9931/v1",
            "RUST_GATEWAY_PORT":"8088",
            "RUST_MAX_CONCURRENT":"1",
            "RUST_MAX_OUTPUT_TOKENS":"1024",
            "AGENT_ADMIN_TOKEN":args.token or env.get("AGENT_ADMIN_TOKEN") or secrets.token_urlsafe(32),
        })
        print("Starting local stack. Keep all three services bound to 127.0.0.1.",flush=True)
        print("Studio: http://127.0.0.1:8000/studio",flush=True)
        print("Admin token:",env["AGENT_ADMIN_TOKEN"],flush=True)
        for index,(name,cmd,cwd) in enumerate(commands):
            print("Starting",name,flush=True)
            p=subprocess.Popen(cmd,cwd=cwd,env=env,**process_group_options())
            processes.append(p)
            if index==0:wait("http://127.0.0.1:9931/v1/models",p,180)
            if index==1:wait("http://127.0.0.1:8088/health",p,180)
            if index==2:wait("http://127.0.0.1:8000/openapi.json",p,60)
        print("Local AI stack is ready. Ctrl+C to stop.",flush=True)
        while all(p.poll() is None for p in processes):time.sleep(.5)
        raise RuntimeError("A local service stopped unexpectedly")
    except (RuntimeError,OSError) as exc:
        print(f"Startup error: {exc}",file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopping local services.",flush=True)
        return 0
    finally:
        for p in reversed(processes):
            terminate_tree(p)
        for p in reversed(processes):
            try:
                p.wait(timeout=6)
            except subprocess.TimeoutExpired:
                terminate_tree(p, force=True)
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:pass

if __name__=="__main__":raise SystemExit(main())
