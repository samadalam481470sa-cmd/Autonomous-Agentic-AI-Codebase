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
    model:str|None=Field(default=None,max_length=120)

def config(requested=None):
    """Resolve the model for a proposal; a request may only name a catalog id."""
    from .models import resolve
    try:
        chosen=resolve(requested)
    except ValueError as error:
        message=str(error)
        status=503 if message.startswith("No model is configured") else 400
        raise HTTPException(status,message)
    return chosen["base_url"],chosen["model"],chosen["api_key"]

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
    base,model,key=config(body.model) if body.model else config()
    prompt=("You are editing exactly one source file. Return ONLY the complete updated file text, "
            "without markdown, explanation, or file separators. Preserve unrelated behavior. "
            "Do not fabricate test results. Follow the instruction and existing code style.")
    user=f"File: {body.path}\nInstruction: {body.instruction}\nOriginal file:\n{old}"
    try:
        async with httpx.AsyncClient(timeout=180,trust_env=os.getenv('LOCAL_MODEL_ONLY')!='1',follow_redirects=False) as client:
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
