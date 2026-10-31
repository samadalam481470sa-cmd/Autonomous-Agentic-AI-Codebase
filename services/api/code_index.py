"""Incremental lexical code search; SQLite FTS5, local-only."""
import hashlib,os,re,sqlite3
from pathlib import Path
from fastapi import APIRouter,Header
from pydantic import BaseModel,Field
from .engine import workspace
from .studio import authorize
router=APIRouter(prefix="/api/index",tags=["index"])
SKIP={".git",".agent","node_modules","target","dist","build",".venv","__pycache__"}
class Request(BaseModel):
 project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
class Query(Request):
 query:str=Field(min_length=1,max_length=200)
def db(project):
 path=workspace(project)/".agent"/"index.sqlite3"
 path.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(path)
 c.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,hash TEXT)")
 c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(path UNINDEXED,line UNINDEXED,body)")
 return c
@router.post("/refresh")
def refresh(body:Request,authorization:str|None=Header(default=None)):
 authorize(authorization)
 root=workspace(body.project);c=db(body.project);updated=0;scanned=0
 with c:
  for base,dirs,files in os.walk(root,followlinks=False):
   dirs[:]=[x for x in dirs if x not in SKIP and not (Path(base)/x).is_symlink()]
   for name in files:
    p=Path(base)/name
    if p.is_symlink() or p.suffix.lower() not in {".py",".rs",".ts",".tsx",".js",".go",".java",".cpp",".sql",".md",".json"}:continue
    if scanned>=10000:break
    scanned+=1
    try:
     if p.stat().st_size>1000000:continue
     data=p.read_bytes();content=data.decode("utf-8")
    except (OSError,UnicodeError):continue
    rel=p.relative_to(root).as_posix();digest=hashlib.sha256(data).hexdigest()
    old=c.execute("SELECT hash FROM files WHERE path=?",(rel,)).fetchone()
    if old and old[0]==digest:continue
    c.execute("DELETE FROM chunks WHERE path=?",(rel,))
    lines=content.splitlines()
    c.executemany("INSERT INTO chunks(path,line,body) VALUES(?,?,?)",[(rel,str(i+1),"\n".join(lines[i:i+80])) for i in range(0,len(lines),80)])
    c.execute("INSERT INTO files VALUES(?,?) ON CONFLICT(path) DO UPDATE SET hash=excluded.hash",(rel,digest));updated+=1
   if scanned>=10000:break
 c.close()
 return {"scanned":scanned,"updated":updated,"limit":10000}
@router.post("/search")
def search(body:Query,authorization:str|None=Header(default=None)):
 authorize(authorization)
 words=re.findall(r"\w{2,}",body.query)[:10]
 if not words:return {"results":[]}
 expression=" OR ".join('"'+w+'"' for w in words)
 with db(body.project) as c:
  rows=c.execute("SELECT path,line,snippet(chunks,2,'[',']','...',16) FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT 30",(expression,)).fetchall()
 return {"results":[{"path":r[0],"line":int(r[1]),"excerpt":r[2]} for r in rows]}
