"""Optional out-of-process AgenticSeek integration. No upstream code vendored.

Only loopback is accepted. The external service must be installed and operated
separately, with its own security configuration and GPL obligations.
"""
import os
from urllib.parse import urlsplit
import httpx

from .hardening import url_problem

class AgenticSeekUnavailable(RuntimeError):
    pass

def config():
    url=os.getenv("AGENTICSEEK_URL","").rstrip("/")
    token=os.getenv("AGENTICSEEK_API_TOKEN","")
    if not url or not token:
        raise AgenticSeekUnavailable("Set AGENTICSEEK_URL and AGENTICSEEK_API_TOKEN to enable AgenticSeek.")
    parsed=urlsplit(url)
    if parsed.scheme!="http" or parsed.hostname not in ("127.0.0.1","localhost","::1") or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("","/"):
        raise AgenticSeekUnavailable("AgenticSeek must run on a loopback HTTP address without URL credentials.")
    problem=url_problem(url,allow_loopback=True)
    if problem:
        raise AgenticSeekUnavailable("AgenticSeek URL rejected: "+problem)
    return url,token

async def delegate(query):
    if not isinstance(query,str) or not 1<=len(query)<=12000:
        raise ValueError("Invalid query length")
    url,token=config()
    async with httpx.AsyncClient(timeout=120,follow_redirects=False,trust_env=False) as client:
        response=await client.post(url+"/query",headers={"Authorization":"Bearer "+token},json={"query":query,"tts_enabled":False})
        response.raise_for_status()
        data=response.json()
    if not isinstance(data,dict):
        raise AgenticSeekUnavailable("Unexpected AgenticSeek response")
    return {"answer":str(data.get("answer",""))[:20000],"status":str(data.get("status",""))[:200],"agent_name":str(data.get("agent_name",""))[:100],"success":str(data.get("success",""))[:20]}
