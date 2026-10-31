"""Authenticated local coding workspace with human-approved file changes.

This module intentionally never executes arbitrary code. Preview is a
sandboxed iframe for user-authored HTML, not a process/container sandbox.
"""
import difflib
import hashlib
import hmac
import os
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .engine import safe_path, workspace

router=APIRouter(prefix="/api/studio",tags=["studio"])
MAX_BYTES=200_000

def authorize(value):
    secret=os.getenv("AGENT_ADMIN_TOKEN","")
    if not secret or not value or not hmac.compare_digest(value,"Bearer "+secret):
        raise HTTPException(403,"Administrator token required")

class FileRequest(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    path:str=Field(min_length=1,max_length=512)

class ChangeRequest(FileRequest):
    content:str=Field(max_length=MAX_BYTES)
    expected_sha256:str|None=None

def resolve(project,path):
    if path.startswith(".agent/") or path==".agent" or path.startswith(".git/") or path==".git":
        raise HTTPException(403,"Internal metadata cannot be edited")
    try: return safe_path(project,path)
    except ValueError as e: raise HTTPException(400,str(e))

def digest(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def current(path):
    if not path.exists(): return ""
    if not path.is_file() or path.stat().st_size>MAX_BYTES:
        raise HTTPException(413,"Not a small text file")
    try: return path.read_text(encoding="utf-8")
    except UnicodeError: raise HTTPException(415,"Binary files are not supported")

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
    p=resolve(body.project,body.path)
    old=current(p)
    if not body.expected_sha256 or not hmac.compare_digest(body.expected_sha256,digest(old)):
        raise HTTPException(409,"File changed since diff; review again")
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.is_symlink(): raise HTTPException(403,"Symlink edits forbidden")
    p.write_text(body.content,encoding="utf-8")
    return {"saved":True,"sha256":digest(body.content),"path":body.path}

@router.post("/preview")
def preview(body:FileRequest,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if not body.path.lower().endswith((".html",".htm")): raise HTTPException(400,"HTML preview only")
    p=resolve(body.project,body.path)
    return {"html":current(p)}
