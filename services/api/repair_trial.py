"""Bounded autonomous repair trials in a disposable offline Docker workspace.

The agent edits only a disposable snapshot, runs allowlisted tests with no
network, and returns a human-reviewable patch. It never touches live source.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import httpx
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from .studio import authorize,digest
from .engine import workspace
from .execution import ALLOWED_COMMANDS,ALLOWED_IMAGES,IMAGE,docker_mount_source
from .multi_file_agent import check_paths,create_record,generate_text
from .code_agent import config

router=APIRouter(prefix="/api/agent/trial",tags=["autonomous-trials"])
IGNORE={".git",".agent","node_modules",".venv","target","dist","build","__pycache__"}

class TrialRequest(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    paths:list[str]=Field(min_length=1,max_length=8)
    goal:str=Field(min_length=5,max_length=4000)
    test_command:str=Field(default="python -m compileall -q .")
    attempts:int=Field(default=2,ge=1,le=3)

def snapshot(root,destination,max_files=10000,max_bytes=100_000_000):
    count=0;size=0
    for base,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if d not in IGNORE and not (Path(base)/d).is_symlink()]
        for name in files:
            src=Path(base)/name
            if src.is_symlink():continue
            try:stat=src.stat()
            except OSError:continue
            count+=1;size+=stat.st_size
            if count>max_files or size>max_bytes:
                raise HTTPException(413,"Repository snapshot exceeds trial limits")
            dst=destination/src.relative_to(root)
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src,dst)
    return count

def trial_command(root,command):
    if command not in ALLOWED_COMMANDS:
        raise HTTPException(403,"Test command is not allowlisted")
    if IMAGE not in ALLOWED_IMAGES:
        raise HTTPException(403,"Execution image not allowlisted")
    args=["docker","run","--rm","--network","none","--read-only","--cap-drop","ALL",
          "--security-opt","no-new-privileges","--pids-limit","64",
          "--memory","512m","--cpus","1","--user","65534:65534",
          "--tmpfs","/tmp:rw,noexec,nosuid,size=64m",
          "--mount",f"type=bind,src={docker_mount_source(root)},dst=/workspace,readonly",
          "--workdir","/workspace",IMAGE,"sh","-c",command]
    try:
        run=subprocess.run(args,capture_output=True,text=True,timeout=60,check=False)
    except FileNotFoundError:
        raise HTTPException(503,"Docker is not installed")
    except subprocess.TimeoutExpired:
        return {"exit_code":124,"output":"Test exceeded 60-second timeout"}
    return {"exit_code":run.returncode,"output":(run.stdout+"\n"+run.stderr)[-7000:]}

@router.post("/run")
async def run_trial(body:TrialRequest,authorization:str|None=Header(default=None),
                    x_confirm_execution:str|None=Header(default=None)):
    authorize(authorization)
    if x_confirm_execution!="approve":
        raise HTTPException(428,"Explicit approval required to execute trial tests")
    if os.getenv("ENABLE_ISOLATED_EXECUTION")!="1":
        raise HTTPException(503,"Enable Docker-based isolated execution first")
    if os.getenv("LOCAL_MODEL_ONLY")!="1":
        raise HTTPException(403,"Autonomous trials require an explicitly local model")
    if body.test_command not in ALLOWED_COMMANDS:
        raise HTTPException(403,"Unapproved test command")
    selected=check_paths(body.project,body.paths)
    root=workspace(body.project)
    base,model,key=config()
    result_log=[]
    updated={}
    with tempfile.TemporaryDirectory(prefix="agentic-trial-") as temporary:
        trial=Path(temporary)
        snapshot(root,trial)
        async with httpx.AsyncClient(timeout=180,trust_env=False,follow_redirects=False) as client:
            for attempt in range(body.attempts):
                for name,_,old in selected:
                    target=trial/name
                    previous=target.read_text(encoding="utf-8") if target.exists() else ""
                    diagnosis=result_log[-1]["output"][-3000:] if result_log else ""
                    prompt=f"Goal: {body.goal}\nFile: {name}\nCurrent file:\n{previous[:60000]}\nPrevious test failure:\n{diagnosis}\nFix the code while preserving unrelated behavior."
                    try:
                        generated=await generate_text(client,base,model,key,prompt)
                    except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
                        raise HTTPException(502,"Model failed to generate a valid trial patch")
                    if not generated or len(generated.encode("utf-8"))>120000:
                        raise HTTPException(502,"Model generated an empty or oversized file")
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_text(generated,encoding="utf-8")
                    updated[name]=generated
                output=await asyncio.to_thread(trial_command,trial,body.test_command)
                result_log.append({"attempt":attempt+1,**output})
                if output["exit_code"]==0:
                    break
    import difflib
    changes=[]
    for name,_,old in selected:
        replacement=updated[name]
        changes.append({"path":name,"expected_sha256":digest(old),"content":replacement,
            "diff":"".join(difflib.unified_diff(
                old.splitlines(keepends=True),replacement.splitlines(keepends=True),
                fromfile="current/"+name,tofile="proposed/"+name))})
    proposal=create_record(body.project,changes)
    return {"trial_passed":result_log[-1]["exit_code"]==0,
            "attempts":len(result_log),"tests":result_log,
            "proposal":proposal,"live_source_modified":False}
