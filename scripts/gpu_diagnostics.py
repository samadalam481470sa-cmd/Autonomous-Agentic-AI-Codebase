"""Read-only local hardware report. No driver installation or remote calls."""
import json
import platform
import shutil
import subprocess
import sys

def probe(command):
    if not shutil.which(command[0]):return None
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=5,check=False)
        return result.stdout.strip()[:4000] if result.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):return None

def report():
    return {
        "platform":platform.platform(),
        "cpu":platform.processor() or platform.machine(),
        "nvidia_gpus":probe(["nvidia-smi","--query-gpu=name,memory.total,driver_version","--format=csv,noheader"]),
        "apple_metal_possible":sys.platform=="darwin" and platform.machine()=="arm64",
        "rocm_detected":shutil.which("rocminfo") is not None,
        "llama_server_detected":shutil.which("llama-server") is not None,
        "cargo_detected":shutil.which("cargo") is not None,
        "note":"Detection is informational. Verify actual inference backend and model compatibility separately."
    }
if __name__=="__main__":print(json.dumps(report(),indent=2))
