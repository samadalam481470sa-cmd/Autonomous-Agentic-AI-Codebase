"""FastAPI app and standalone browser UI."""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import load_env_file
# Load repository .env before the imports below read configuration at module
# scope. Explicit environment variables take precedence.
load_env_file()
from .engine import history, respond, tool, workspace, ModelNotConfigured
from . import hardening
from .security import SecurityMiddleware, audit as security_audit, status as security_status

app=FastAPI(title="Autonomous Agentic AI Codebase",version="0.2.0")
app.add_middleware(SecurityMiddleware)
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
from .code_index import router as code_index_router
app.include_router(code_index_router)
from .code_agent import router as code_agent_router
app.include_router(code_agent_router)
from .ide_rewrite import router as ide_rewrite_router
app.include_router(ide_rewrite_router)
from .multi_file_agent import router as multi_file_agent_router
app.include_router(multi_file_agent_router)
from .voice import router as local_voice_router
app.include_router(local_voice_router)
from .learning import router as learning_router
app.include_router(learning_router)
from .repair_trial import router as repair_trial_router
app.include_router(repair_trial_router)
from .ai_features import router as ai_features_router
app.include_router(ai_features_router)
from .orchestrator import router as orchestrator_router
app.include_router(orchestrator_router)
import sys
BASE=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[2]))
WEB=BASE/"apps"/"web"/"index.html"
app.mount('/assets',StaticFiles(directory=str(WEB.parent/'assets')),name='assets')
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
    except ModelNotConfigured as e: raise HTTPException(503,str(e))
    except Exception as e: raise HTTPException(502,"Model provider error: "+type(e).__name__)
@app.post("/api/chat/stream")
async def chat_stream(body:ChatRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    if os.getenv("LOCAL_MODEL_ONLY")!="1":
        raise HTTPException(409,"Local streaming requires LOCAL_MODEL_ONLY=1; use /api/chat otherwise")
    from .chat_stream import stream_local_chat
    return StreamingResponse(
        stream_local_chat(body.project,body.message),
        media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no","X-Content-Type-Options":"nosniff"}
    )

@app.post("/api/tool")
def execute(body:ToolRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)
    if body.name=="run_command": raise HTTPException(403,"Commands cannot be invoked via the public tool endpoint")
    try: return {"result":tool(body.project,body.name,body.arguments)}
    except ValueError as e: raise HTTPException(400,str(e))


# Optional, explicitly authorized delegation to an independently deployed agent.
from .agenticseek import delegate, AgenticSeekUnavailable
from .agents import plan as create_plan, load as load_plan
from .security import authorize as require_admin

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


DASHBOARD = BASE / "apps" / "dashboard" / "dist"
DASHBOARD_BUILD_HELP = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>Aetherion OmniForge dashboard</title></head><body style=\"font:15px system-ui;"
    "background:#0b0d10;color:#e6e9ef;padding:40px\"><h1>Dashboard not built</h1>"
    "<p>Build the front end, then restart the API:</p>"
    "<pre style=\"background:#161a20;padding:16px;border-radius:8px\">"
    "cd apps/dashboard\nnpm ci\nnpm run build</pre>"
    "<p>The prebuilt bundle is committed; if it is missing run the command above.</p>"
    "</body></html>"
)
if (DASHBOARD / "assets").is_dir():
    app.mount("/dashboard/assets", StaticFiles(directory=str(DASHBOARD / "assets")),
              name="dashboard-assets")

# Refuse to serve secrets, databases or repository metadata through a static
# mount. This runs at import so a misconfiguration is visible in the audit log
# before the first request.
_STATIC_ISSUES = hardening.static_mount_problems(app)
if _STATIC_ISSUES:
    security_audit("startup.static_exposure", str(_STATIC_ISSUES)[:800])


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():
    index = DASHBOARD / "index.html"
    if not index.is_file():
        return HTMLResponse(DASHBOARD_BUILD_HELP, status_code=503)
    return index.read_text(encoding="utf-8")


@app.get("/api/security/status")
def get_security_status(request: Request, limit: int = 20,
                        authorization: str | None = Header(default=None)):
    require_admin(authorization)
    payload = security_status(limit)
    payload["client"] = request.client.host if request.client else "unknown"
    payload["request_id"] = getattr(request.state, "request_id", "")
    return payload


@app.get("/api/security/coverage")
def get_security_coverage(authorization: str | None = Header(default=None)):
    """Machine-readable control coverage for the 50 tracked attack classes."""
    require_admin(authorization)
    return {"summary": hardening.summary(), "threats": hardening.THREATS}


@app.get("/api/security/audit/verify")
def verify_audit_trail(authorization: str | None = Header(default=None)):
    """Verify the tamper-evident audit hash chain."""
    require_admin(authorization)
    from .security import verify_audit_chain
    return verify_audit_chain()
