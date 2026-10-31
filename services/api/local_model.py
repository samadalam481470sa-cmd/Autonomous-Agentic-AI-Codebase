"""Local-only OpenAI-compatible model gateway configuration and diagnostics."""
import os
from urllib.parse import urlsplit
from fastapi import APIRouter, Header, HTTPException
from .studio import authorize
router=APIRouter(prefix="/api/local-model",tags=["local-model"])

def local_url():
    url=os.getenv("LOCAL_MODEL_BASE_URL","http://127.0.0.1:11434/v1").rstrip("/")
    parsed=urlsplit(url)
    if parsed.scheme!="http" or parsed.hostname not in ("localhost","127.0.0.1","::1") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Local inference endpoint must be loopback HTTP")
    if parsed.path not in ("/v1","/api/v1"):
        raise ValueError("Expected a loopback OpenAI-compatible /v1 endpoint")
    return url

def model_settings():
    return {"base_url":local_url(),"model":os.getenv("LOCAL_MODEL_NAME","qwen2.5-coder:7b"),"local":True}

@router.get("/config")
def config(authorization:str|None=Header(default=None)):
    authorize(authorization)
    try:return model_settings()
    except ValueError as e:raise HTTPException(400,str(e))
