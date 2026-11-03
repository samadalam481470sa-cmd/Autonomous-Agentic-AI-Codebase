"""Explicitly approved, resource-limited Docker execution.

Not a security boundary against container escape; deploy on a dedicated VM.
Never mount the Docker socket inside the agent container.
"""
import os
import re
import subprocess
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from .studio import authorize
from .engine import workspace

router=APIRouter(prefix="/api/execution",tags=["execution"])
IMAGE=os.getenv("EXECUTION_IMAGE","python:3.12-alpine")
ALLOWED_IMAGES={"python:3.12-alpine","node:22-alpine"}
ALLOWED_COMMANDS={"python -m pytest -q","python -m compileall -q .","npm test -- --runInBand","npm run build"}
def docker_mount_source(path, platform=os.name):
    """Return a bind source accepted by Docker Desktop and Docker Engine.

    Docker Desktop on Windows accepts both separators, but forward slashes avoid
    escaping problems in the --mount value. POSIX paths are left untouched.
    """
    text = str(path)
    return text.replace("\\", "/") if platform == "nt" else text

class RunRequest(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    command:str=Field(min_length=1,max_length=150)

@router.post("/run")
def run(body:RunRequest,authorization:str|None=Header(default=None),x_confirm_execution:str|None=Header(default=None)):
    authorize(authorization)
    if x_confirm_execution!="approve":raise HTTPException(428,"Human approval required")
    if os.getenv("ENABLE_ISOLATED_EXECUTION")!="1":raise HTTPException(503,"Execution disabled")
    if body.command not in ALLOWED_COMMANDS:raise HTTPException(403,"Command not allowlisted")
    if IMAGE not in ALLOWED_IMAGES:raise HTTPException(403,"Image not allowlisted")
    root=workspace(body.project)
    if not root.is_dir():raise HTTPException(400,"Workspace missing")
    # No shell on host; no daemon socket mount; no network; read-only source.
    args=["docker","run","--rm","--network","none","--read-only",
          "--cap-drop","ALL","--security-opt","no-new-privileges",
          "--pids-limit","64","--memory","512m","--cpus","1",
          "--user","65534:65534","--tmpfs","/tmp:rw,noexec,nosuid,size=64m",
          "--mount",f"type=bind,src={docker_mount_source(root)},dst=/workspace,readonly",
          "--workdir","/workspace",IMAGE,
          "sh","-c",body.command]
    try:
        result=subprocess.run(args,capture_output=True,text=True,timeout=45,check=False)
        return {"exit_code":result.returncode,"stdout":result.stdout[-12000:],"stderr":result.stderr[-4000:],"command":body.command}
    except FileNotFoundError:raise HTTPException(503,"Docker unavailable on host")
    except subprocess.TimeoutExpired:raise HTTPException(408,"Execution timed out")
