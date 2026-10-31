import base64
import pytest
from fastapi import HTTPException
from services.api.voice import voice_url,decode_wav

def test_voice_requires_loopback(monkeypatch):
    for url in ("https://example.com","http://192.168.1.3:8089","http://user:pass@127.0.0.1:8089"):
        monkeypatch.setenv("WHISPER_LOCAL_URL",url)
        with pytest.raises(HTTPException):
            voice_url()
    monkeypatch.setenv("WHISPER_LOCAL_URL","http://127.0.0.1:8089")
    assert voice_url()=="http://127.0.0.1:8089"

def test_reject_invalid_audio():
    for payload in ("bad","",base64.b64encode(b"not a wave").decode()):
        with pytest.raises(HTTPException):
            decode_wav(payload)

def test_accepts_riff_wave_header():
    wav=b"RIFF"+bytes(4)+b"WAVE"+bytes(36)
    assert decode_wav(base64.b64encode(wav).decode())==wav
