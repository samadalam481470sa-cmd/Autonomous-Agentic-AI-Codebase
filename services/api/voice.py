"""Opt-in loopback-only speech recognition using a separately installed whisper.cpp server.

Audio bytes are forwarded only to localhost. No browser cloud speech APIs.
"""
import base64
import binascii
import os
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from .studio import authorize

router=APIRouter(prefix="/api/voice",tags=["local-voice"])
MAX_AUDIO=6*1024*1024

class TranscriptRequest(BaseModel):
    wav_base64:str=Field(min_length=16,max_length=MAX_AUDIO*2)

def voice_url():
    url=os.getenv("WHISPER_LOCAL_URL","http://127.0.0.1:8089").rstrip("/")
    parsed=urlsplit(url)
    if parsed.scheme!="http" or parsed.hostname not in {"localhost","127.0.0.1","::1"}:
        raise HTTPException(400,"Voice recognition requires localhost whisper.cpp")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise HTTPException(400,"Invalid local voice URL")
    return url

def decode_wav(value):
    try:audio=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error):raise HTTPException(400,"Invalid base64 WAV")
    if len(audio)>MAX_AUDIO or len(audio)<44 or audio[:4]!=b"RIFF" or audio[8:12]!=b"WAVE":
        raise HTTPException(400,"Expected a WAV recording under 6 MiB")
    return audio

@router.post("/transcribe")
async def transcribe(body:TranscriptRequest,authorization:str|None=Header(default=None)):
    authorize(authorization)
    audio=decode_wav(body.wav_base64)
    url=voice_url()
    try:
        async with httpx.AsyncClient(timeout=90,trust_env=False,follow_redirects=False) as client:
            response=await client.post(url+"/inference",
                files={"file":("recording.wav",audio,"audio/wav")},
                data={"response_format":"json"})
            response.raise_for_status()
            output=response.json()
    except (httpx.HTTPError,ValueError):
        raise HTTPException(503,"Local speech server unavailable")
    text=output.get("text") if isinstance(output,dict) else None
    if not isinstance(text,str):
        raise HTTPException(502,"Speech server returned an invalid transcript")
    return {"text":text[:12000],"local":True}
