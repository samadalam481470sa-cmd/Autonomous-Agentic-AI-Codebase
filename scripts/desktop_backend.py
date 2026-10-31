"""Frozen backend entry point. Build with PyInstaller on each target OS."""
import os
from pathlib import Path
import uvicorn
if __name__=="__main__":
    os.environ.setdefault("LOCAL_MODEL_ONLY","1")
    uvicorn.run("services.api.main:app",host="127.0.0.1",port=8000,workers=1,log_level="warning")
