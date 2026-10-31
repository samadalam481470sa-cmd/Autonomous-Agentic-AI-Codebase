"""FastAPI app and standalone browser UI."""
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .engine import history, respond, tool, workspace

app=FastAPI(title="Autonomous Agentic AI Codebase",version="0.2.0")
from .studio import router as studio_router
app.include_router(studio_router)
from .execution import router as execution_router
app.include_router(execution_router)
from .languages import router as languages_router
from .local_model import router as local_model_router
app.include_router(languages_router)
app.include_router(local_model_router)
from .project_store import router as project_router
app.include_router(project_router)
import sys
BASE=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[2]))
WEB=BASE/"apps"/"web"/"index.html"
class ChatRequest(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    message:str=Field(min_length=1,max_length=12000)
class ToolRequest(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name:str
    arguments:dict={}
@app.get("/",response_class=HTMLResponse)
def home(): return WEB.read_text()
@app.get("/health")
def health(): return {"status":"ok"}
@app.get("/api/projects/{project}/history")
def get_history(project:str, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    try: workspace(project);return {"messages":history(project)}
    except ValueError as e: raise HTTPException(400,str(e))
@app.post("/api/chat")
async def chat(body:ChatRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    try: return {"answer":await respond(body.project,body.message)}
    except Exception as e: raise HTTPException(502,"Model provider error: "+type(e).__name__)
@app.post("/api/tool")
def execute(body:ToolRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    if body.name=="run_command": raise HTTPException(403,"Commands cannot be invoked via the public tool endpoint")
    try: return {"result":tool(body.project,body.name,body.arguments)}
    except ValueError as e: raise HTTPException(400,str(e))


# Optional, explicitly authorized delegation to an independently deployed agent.
import hmac
import os
from .agenticseek import delegate, AgenticSeekUnavailable
from .agents import plan as create_plan, load as load_plan


def require_admin(authorization: str | None):
    secret = os.getenv('AGENT_ADMIN_TOKEN', '')
    if not secret or not authorization or not hmac.compare_digest(authorization, 'Bearer ' + secret):
        raise HTTPException(403, 'Agent admin token required; set AGENT_ADMIN_TOKEN')

@app.post('/api/integrations/agenticseek/query')
async def agenticseek_query(body: ChatRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    try:
        return await delegate(body.message)
    except AgenticSeekUnavailable as exc:
        raise HTTPException(503, str(exc))
    except Exception:
        raise HTTPException(502, 'External agent unavailable')

@app.post('/api/projects/plan')
def create_project_plan(body: ChatRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    try:
        return create_plan(body.project, body.message)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.get('/api/projects/{project}/plan')
def get_project_plan(project: str, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    try:
        return load_plan(project)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc))


@app.get("/studio",response_class=HTMLResponse)
def studio_page():
    return (WEB.parent/"studio.html").read_text(encoding="utf-8")
