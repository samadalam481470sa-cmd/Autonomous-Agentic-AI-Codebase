"""Agent tools, storage and OpenAI-compatible tool calling."""
import json
import os
import re
import sqlite3
import subprocess
import uuid
from pathlib import Path
import httpx

ROOT = Path(os.getenv("WORKSPACE_ROOT", "./workspaces")).resolve()
DB = Path(os.getenv("DB_PATH", "./database/agent.sqlite3")).resolve()
TOOLS = [
 {"type":"function","function":{"name":"list_files","description":"List project files","parameters":{"type":"object","properties":{"path":{"type":"string"}}}}},
 {"type":"function","function":{"name":"read_file","description":"Read UTF-8 file","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
 
 {"type":"function","function":{"name":"search_files","description":"Search text in project files","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}}
]
def workspace(project):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",project): raise ValueError("Invalid project name")
    path = (ROOT/project).resolve()
    path.mkdir(parents=True,exist_ok=True)
    return path

def safe_path(project,path):
    root=workspace(project)
    result=(root/path).resolve()
    if not result.is_relative_to(root): raise ValueError("Path outside workspace")
    return result

def tool(project,name,args):
    if name in ("write_file","run_command"):
        return "Direct agent writes and host commands are disabled. Use the authenticated Studio diff/approval workflow or approved isolated execution endpoint."

    try:
        if name=="list_files":
            p=safe_path(project,args.get("path","."))
            return json.dumps(sorted(str(x.relative_to(workspace(project))) for x in p.rglob("*") if x.is_file())[:200])
        if name=="read_file":
            p=safe_path(project,args["path"])
            if p.stat().st_size>100_000: return "File exceeds 100KB limit"
            return p.read_text(encoding="utf-8")
        if name=="write_file":
            p=safe_path(project,args["path"])
            content=args["content"]
            if len(content)>100_000: return "Write exceeds 100KB limit"
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(content,encoding="utf-8")
            return "Wrote "+str(p.relative_to(workspace(project)))
        if name=="search_files":
            q=args["query"]
            if not q or len(q)>100: return "Invalid query"
            matches=[]
            for p in workspace(project).rglob("*"):
                if not p.is_file() or p.stat().st_size>100_000: continue
                try:
                    for n,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1):
                        if q.lower() in line.lower(): matches.append(f"{p.relative_to(workspace(project))}:{n}: {line[:160]}")
                        if len(matches)>=60: return json.dumps(matches)
                except (UnicodeError,OSError): continue
            return json.dumps(matches)
        if name=="run_command":
            if os.getenv("ALLOW_COMMANDS")!="1": return "Command execution disabled. Set ALLOW_COMMANDS=1 only in an isolated trusted environment."
            command=args["command"]
            if not isinstance(command,str) or len(command)>300: return "Invalid command"
            result=subprocess.run(command,shell=True,cwd=workspace(project),capture_output=True,text=True,timeout=15)
            return json.dumps({"exit_code":result.returncode,"stdout":result.stdout[-5000:],"stderr":result.stderr[-2000:]})
        return "Unknown tool"
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as e:
        return "Tool error: "+str(e)

def db():
    DB.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, project TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    return con

def history(project):
    with db() as con:
        return [{"role":r,"content":c} for r,c in con.execute("SELECT role,content FROM messages WHERE project=? ORDER BY rowid DESC LIMIT 30",(project,)).fetchall()[::-1]]

def save(project,role,content):
    with db() as con:
        con.execute("INSERT INTO messages(id,project,role,content) VALUES(?,?,?,?)",(str(uuid.uuid4()),project,role,content))

async def respond(project,message):
    save(project,"user",message)
    key=os.getenv("MODEL_API_KEY","")
    if not key: return "Configure MODEL_API_KEY, MODEL_BASE_URL and MODEL_NAME to enable model responses."
    msgs=[{"role":"system","content":"You are an AI software engineer. Use tools to inspect and edit project files. Do not claim to have executed actions without tool results. Ask before risky or destructive actions."}]+history(project)
    base=os.getenv("MODEL_BASE_URL","https://api.openai.com/v1").rstrip("/")
    async with httpx.AsyncClient(timeout=90) as client:
        for _ in range(8):
            r=await client.post(base+"/chat/completions",headers={"Authorization":"Bearer "+key},json={"model":os.getenv("MODEL_NAME","gpt-4.1-mini"),"messages":msgs,"tools":TOOLS,"tool_choice":"auto"})
            r.raise_for_status()
            choice=r.json()["choices"][0]["message"]
            calls=choice.get("tool_calls") or []
            if not calls:
                answer=choice.get("content") or "(No response)"
                save(project,"assistant",answer)
                return answer
            msgs.append(choice)
            for call in calls:
                fn=call["function"]
                try: args=json.loads(fn.get("arguments","{}"))
                except json.JSONDecodeError: args={}
                result=tool(project,fn["name"],args)
                msgs.append({"role":"tool","tool_call_id":call["id"],"content":result})
        answer="Reached the tool-call limit. Review project files and continue in a new turn."
        save(project,"assistant",answer)
        return answer
