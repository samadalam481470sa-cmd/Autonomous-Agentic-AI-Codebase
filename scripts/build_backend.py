"""Build a per-OS Python executable, including the browser UI assets."""
import subprocess
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
separator=";" if sys.platform=="win32" else ":"
cmd=[sys.executable,"-m","PyInstaller","--noconfirm","--clean","--onedir","--name","agentic-backend",
     "--distpath",str(root/"dist"/"backend-stage"),
     "--workpath",str(root/"build"/"pyinstaller"),
     "--specpath",str(root/"build"),
     "--collect-all","uvicorn","--collect-submodules","services.api",
     "--add-data",f"{root/'apps'/'web'}{separator}apps/web",
     str(root/"scripts"/"desktop_backend.py")]
subprocess.check_call(cmd,cwd=root)
import shutil
src=root/"dist"/"backend-stage"/"agentic-backend"
dst=root/"dist"/"backend"
if dst.exists():shutil.rmtree(dst)
shutil.copytree(src,dst)
print("Bundled backend:",dst)
