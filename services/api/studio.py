"""Authenticated local coding workspace with human-approved file changes.

This module intentionally never executes arbitrary code. Preview is a
sandboxed iframe for user-authored HTML, not a process/container sandbox.
"""
import difflib
import hashlib
import hmac
import os
import tempfile
import threading
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .engine import safe_path, workspace
from . import checkpoints, turns
from .security import authorize as _authorize

router=APIRouter(prefix="/api/studio",tags=["studio"])
MAX_BYTES=200_000
WRITE_LOCK=threading.RLock()

def authorize(value, scope="admin"):
    """Compatibility wrapper around the shared hardened authenticator."""
    _authorize(value, scope)

class FileRequest(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    path:str=Field(min_length=1,max_length=512)

class RestoreRequest(FileRequest):
    checkpoint_id:str=Field(pattern=r"^[a-f0-9]{32}$")
    expected_sha256:str=Field(pattern=r"^[a-f0-9]{64}$")

class ChangeRequest(FileRequest):
    content:str=Field(max_length=MAX_BYTES)
    expected_sha256:str|None=None

def resolve(project,path):
    # Prevent accidental edits to checkpoint/proposal metadata at any depth.
    raw=Path(path)
    if raw.is_absolute() or ".." in raw.parts:
        raise HTTPException(400,"Path must be relative to the workspace")
    if any(part in (".agent",".git") for part in raw.parts):
        raise HTTPException(403,"Internal metadata cannot be edited")
    try:
        root=workspace(project)
        target=safe_path(project,path)
        # A symlink inside the workspace must not hide an unrelated target.
        probe=root
        for part in raw.parts:
            probe=probe/part
            if probe.is_symlink():
                raise HTTPException(403,"Symlink edits forbidden")
        return target
    except ValueError as e:
        raise HTTPException(400,str(e))

def digest(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def current(path):
    if not path.exists(): return ""
    if not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise HTTPException(413,"Not a small text file")
    try: return path.read_text(encoding="utf-8")
    except UnicodeError: raise HTTPException(415,"Binary files are not supported")

def atomic_text_write(path,content):
    """Write through a sibling temporary file then atomically replace."""
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():
        raise HTTPException(403,"Symlink edits forbidden")
    staged=None
    try:
        with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,
                prefix=".studio-save-",delete=False) as handle:
            staged=Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged,path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)

@router.post("/checkpoints")
def checkpoints_for_file(body:FileRequest,authorization:str|None=Header(default=None)):
    authorize(authorization)
    resolve(body.project,body.path)
    return {"checkpoints":checkpoints.recent(body.project,body.path)}

@router.post("/restore")
def restore_checkpoint(body:RestoreRequest,authorization:str|None=Header(default=None),
                       x_confirm_change:str|None=Header(default=None)):
    authorize(authorization)
    if x_confirm_change!="approve":
        raise HTTPException(428,"Explicit human approval required")
    with WRITE_LOCK:
        target=resolve(body.project,body.path)
        data=checkpoints.one(body.project,body.path,body.checkpoint_id)
        exists=target.is_file()
        content=current(target)
        actual=digest(content)
        if (not hmac.compare_digest(body.expected_sha256,actual)
            or bool(data["applied_exists"])!=exists
            or not hmac.compare_digest(data["applied_sha256"],actual)):
            raise HTTPException(409,"File changed since the checkpoint; review the current file")
        previous=data["previous_content"]
        previous_exists=bool(data["previous_exists"])
        # Make restore itself reversible, including deletion of a newly created file.
        undo_id=checkpoints.snapshot(
            body.project,body.path,content,exists,previous,previous_exists
        )
        if previous_exists:
            atomic_text_write(target,previous)
        else:
            target.unlink()
        return {"restored":True,"path":body.path,"exists":previous_exists,
                "sha256":digest(previous),"undo_checkpoint_id":undo_id}

@router.get("/files/{project}")
def files(project:str,authorization:str|None=Header(default=None)):
    authorize(authorization)
    try:
        root=workspace(project)
        result=[]
        for p in root.rglob("*"):
            if len(result)>=500: break
            if p.is_file() and not p.is_symlink() and ".agent" not in p.parts and ".git" not in p.parts:
                result.append(str(p.relative_to(root)))
        return {"files":sorted(result)}
    except ValueError as e: raise HTTPException(400,str(e))

@router.post("/read")
def read(body:FileRequest,authorization:str|None=Header(default=None)):
    authorize(authorization)
    p=resolve(body.project,body.path)
    text=current(p)
    return {"content":text,"sha256":digest(text),"exists":p.exists()}

@router.post("/diff")
def diff(body:ChangeRequest,authorization:str|None=Header(default=None)):
    authorize(authorization)
    p=resolve(body.project,body.path)
    old=current(p)
    return {"diff":"".join(difflib.unified_diff(old.splitlines(keepends=True),body.content.splitlines(keepends=True),fromfile="current/"+body.path,tofile="proposed/"+body.path)),"sha256":digest(old),"changed":old!=body.content}

@router.post("/apply")
def apply(body:ChangeRequest,authorization:str|None=Header(default=None),x_confirm_change:str|None=Header(default=None)):
    authorize(authorization)
    if x_confirm_change!="approve": raise HTTPException(428,"Explicit human approval required")
    with WRITE_LOCK:
        p=resolve(body.project,body.path)
        existed=p.is_file()
        old=current(p)
        if not body.expected_sha256 or not hmac.compare_digest(body.expected_sha256,digest(old)):
            raise HTTPException(409,"File changed since diff; review again")
        if old==body.content and existed:
            return {"saved":True,"sha256":digest(old),"path":body.path,
                    "checkpoint_id":None,"turn_id":None}
        checkpoint_id=checkpoints.snapshot(body.project,body.path,old,existed,body.content)
        atomic_text_write(p,body.content)
        # Group every write of this turn so the whole turn can be reverted.
        turn_id=turns.new_turn()
        turns.record(body.project,turn_id,body.path,checkpoint_id)
        return {"saved":True,"sha256":digest(body.content),
                "path":body.path,"checkpoint_id":checkpoint_id,"turn_id":turn_id}

@router.post("/preview")
def preview(body:FileRequest,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if not body.path.lower().endswith((".html",".htm")): raise HTTPException(400,"HTML preview only")
    p=resolve(body.project,body.path)
    return {"html":current(p)}
