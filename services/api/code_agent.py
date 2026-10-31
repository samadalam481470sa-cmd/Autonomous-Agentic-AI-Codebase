"""Model-assisted code proposals. Generation never writes project files."""
import difflib
import os
import re
import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from .studio import authorize, current, digest, resolve

router=APIRouter(prefix="/api/agent",tags=["agent"])
MAX_RESPONSE_CHARS=190000

class ProposalRequest(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    path:str=Field(min_length=1,max_length=512)
    instruction:str=Field(min_length=4,max_length=4000)

def config():
    if os.getenv("LOCAL_MODEL_ONLY")=="1":
        from .local_model import model_settings
        settings=model_settings()
        return settings["base_url"],settings["model"],"local"
    key=os.getenv("MODEL_API_KEY")
    if not key:
        raise HTTPException(503,"Configure local inference or MODEL_API_KEY")
    return os.getenv("MODEL_BASE_URL","https://api.openai.com/v1").rstrip("/"),os.getenv("MODEL_NAME","gpt-4.1-mini"),key

def strip_fence(value):
    value=value.strip()
    match=re.fullmatch(r"```(?:[\w+#.-]+)?\s*\n(.*?)\n```",value,flags=re.S)
    return match.group(1) if match else value

def proposal_for(path,old,generated):
    generated=strip_fence(generated)
    if not generated or len(generated)>MAX_RESPONSE_CHARS:
        raise HTTPException(502,"Model returned an empty or oversized proposal")
    change="".join(difflib.unified_diff(
        old.splitlines(keepends=True),generated.splitlines(keepends=True),
        fromfile="current/"+path,tofile="proposed/"+path))
    return {"path":path,"content":generated,"expected_sha256":digest(old),
            "proposed_sha256":digest(generated),"diff":change,"changed":generated!=old,
            "requires_approval":True}

@router.post("/propose")
async def propose(body:ProposalRequest,authorization:str|None=Header(default=None)):
    authorize(authorization)
    source=resolve(body.project,body.path)
    old=current(source)
    if len(old)>100000:
        raise HTTPException(413,"File exceeds model context budget; select a smaller file")
    base,model,key=config()
    prompt=("You are editing exactly one source file. Return ONLY the complete updated file text, "
            "without markdown, explanation, or file separators. Preserve unrelated behavior. "
            "Do not fabricate test results. Follow the instruction and existing code style.")
    user=f"File: {body.path}\nInstruction: {body.instruction}\nOriginal file:\n{old}"
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response=await client.post(base+"/chat/completions",
                headers={"Authorization":"Bearer "+key},
                json={"model":model,"messages":[{"role":"system","content":prompt},
                     {"role":"user","content":user}],"temperature":0.1,
                     "max_tokens":min(int(os.getenv("AGENT_PROPOSAL_MAX_TOKENS","4096")),8192)})
            response.raise_for_status()
            generated=response.json()["choices"][0]["message"].get("content")
    except (httpx.HTTPError,KeyError,IndexError,TypeError,ValueError):
        raise HTTPException(502,"Model did not return a valid code proposal")
    if not isinstance(generated,str):
        raise HTTPException(502,"Model did not return file text")
    return proposal_for(body.path,old,generated)
