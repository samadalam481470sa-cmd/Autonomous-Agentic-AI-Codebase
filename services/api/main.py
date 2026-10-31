"""FastAPI app and standalone browser UI."""
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .engine import history, respond, tool, workspace

app=FastAPI(title="Autonomous Agentic AI Codebase",version="0.1.0")
WEB=Path(__file__).resolve().parents[2]/"apps"/"web"/"index.html"
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
def get_history(project:str):
    try: workspace(project);return {"messages":history(project)}
    except ValueError as e: raise HTTPException(400,str(e))
@app.post("/api/chat")
async def chat(body:ChatRequest):
    try: return {"answer":await respond(body.project,body.message)}
    except Exception as e: raise HTTPException(502,"Model provider error: "+type(e).__name__)
@app.post("/api/tool")
def execute(body:ToolRequest):
    if body.name=="run_command": raise HTTPException(403,"Commands cannot be invoked via the public tool endpoint")
    try: return {"result":tool(body.project,body.name,body.arguments)}
    except ValueError as e: raise HTTPException(400,str(e))
