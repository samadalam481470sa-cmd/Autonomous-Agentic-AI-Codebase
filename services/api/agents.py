"""Small deterministic planning layer with explicit bounded task steps.

This is not a substitute for model reasoning. Plans are saved as JSON and
executed only when the user explicitly invokes the separate agent endpoint.
"""
import json
import re
import uuid
from pathlib import Path
from .engine import workspace

def plan(project,goal):
    if not goal.strip() or len(goal)>12000: raise ValueError("Invalid goal")
    tasks=[
      {"id":str(uuid.uuid4()),"role":"architect","instruction":"Identify requirements and files for: "+goal[:2000],"status":"pending"},
      {"id":str(uuid.uuid4()),"role":"coder","instruction":"Implement the requested functionality and document assumptions","status":"pending"},
      {"id":str(uuid.uuid4()),"role":"reviewer","instruction":"Review code, test cases, security and unfinished work","status":"pending"}
    ]
    data={"id":str(uuid.uuid4()),"project":project,"goal":goal,"status":"draft","tasks":tasks}
    root=workspace(project)/".agent"
    root.mkdir(exist_ok=True)
    (root/"plan.json").write_text(json.dumps(data,indent=2),encoding="utf-8")
    return data

def load(project):
    p=workspace(project)/".agent"/"plan.json"
    if not p.exists(): raise FileNotFoundError("No plan; create one first")
    return json.loads(p.read_text(encoding="utf-8"))
