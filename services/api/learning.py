"""Explicit feedback and versioned candidate evaluation for opt-in local adaptation.

Records user-approved examples and evaluates candidate model predictions against
a held-out benchmark. This module does not train model weights on its own.
"""
import json
import os
import sqlite3
import time
import uuid
from fastapi import APIRouter,Header,HTTPException
from pydantic import BaseModel,Field
from .engine import workspace
from .studio import authorize
from . import lifelong

router=APIRouter(prefix="/api/learning",tags=["learning"])
class Feedback(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    prompt:str=Field(min_length=1,max_length=4000)
    accepted_response:str=Field(min_length=1,max_length=16000)
    consent:bool=False
class Evaluation(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    candidate:str=Field(min_length=1,max_length=128)
    passed:int=Field(ge=0,le=1000000)
    total:int=Field(ge=1,le=1000000)
    baseline_passed:int=Field(ge=0,le=1000000)
    min_improvement:float=Field(default=0.0,ge=0,le=1)
class InteractionRating(BaseModel):
    project:str=Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    rating:str=Field(pattern=r"^(up|down)$")
class TrainRequest(BaseModel):
    force:bool=False

def database(project):
    path=workspace(project)/".agent"/"feedback.sqlite3"
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=15)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS feedback(
      id TEXT PRIMARY KEY,prompt TEXT NOT NULL,response TEXT NOT NULL,
      created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS evaluations(
      id TEXT PRIMARY KEY,candidate TEXT NOT NULL,passed INTEGER NOT NULL,
      total INTEGER NOT NULL,baseline INTEGER NOT NULL,
      approved INTEGER NOT NULL,created_at INTEGER NOT NULL);
    """)
    return db

@router.post("/feedback")
def feedback(body:Feedback,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if not body.consent:
        raise HTTPException(428,"Explicit consent required to store training examples")
    ident=uuid.uuid4().hex
    with database(body.project) as db:
        db.execute("INSERT INTO feedback VALUES(?,?,?,?)",
                   (ident,body.prompt,body.accepted_response,int(time.time())))
    return {"id":ident,"stored_locally":True,"trained":False}

@router.post("/evaluation")
def evaluation(body:Evaluation,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if body.passed>body.total or body.baseline_passed>body.total:
        raise HTTPException(400,"Invalid benchmark counts")
    improved=(body.passed-body.baseline_passed)/body.total
    approved=improved>=body.min_improvement and body.passed>=body.baseline_passed
    ident=uuid.uuid4().hex
    with database(body.project) as db:
        db.execute("INSERT INTO evaluations VALUES(?,?,?,?,?,?,?)",
                   (ident,body.candidate,body.passed,body.total,
                    body.baseline_passed,int(approved),int(time.time())))
    return {"evaluation_id":ident,"candidate":body.candidate,"approved":approved,
            "delta":round(improved,6),"model_switched":False}

@router.get("/continuous/status")
def continuous_status(project:str|None=None,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if project is not None and not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",project):
        raise HTTPException(400,"Invalid project name")
    return lifelong.continuous_status(project)

@router.post("/continuous/start")
def continuous_start(authorization:str|None=Header(default=None)):
    authorize(authorization)
    lifelong.state_set("enabled","1")
    lifelong.state_set("paused","0")
    started=lifelong.runtime.start()
    return {"enabled":True,"thread_started":started,"runtime":lifelong.runtime.status()}

@router.post("/continuous/pause")
def continuous_pause(authorization:str|None=Header(default=None)):
    authorize(authorization)
    lifelong.state_set("paused","1")
    return {"paused":True,"runtime":lifelong.runtime.status()}

@router.post("/continuous/tick")
def continuous_tick(authorization:str|None=Header(default=None)):
    authorize(authorization)
    return lifelong.tick(force=True)

@router.get("/{project}/interactions")
def interaction_list(project:str,limit:int=20,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",project):
        raise HTTPException(400,"Invalid project name")
    return {"project":project,"interactions":lifelong.interactions(project,limit)}

@router.post("/{project}/interactions/{interaction_id}/rate")
def interaction_rate(project:str,interaction_id:str,body:InteractionRating,
                     authorization:str|None=Header(default=None)):
    authorize(authorization)
    if body.project!=project:
        raise HTTPException(400,"Project mismatch")
    try:
        return lifelong.rate(project,interaction_id,body.rating)
    except ValueError as error:
        raise HTTPException(400,str(error))

@router.post("/{project}/train")
def train(project:str,body:TrainRequest|None=None,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",project):
        raise HTTPException(400,"Invalid project name")
    return lifelong.train(project,force=bool(body and body.force))

@router.post("/{project}/rollback")
def rollback(project:str,authorization:str|None=Header(default=None)):
    authorize(authorization)
    if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,64}",project):
        raise HTTPException(400,"Invalid project name")
    try:
        return lifelong.rollback(project)
    except ValueError as error:
        raise HTTPException(400,str(error))

@router.get("/{project}/status")
def status(project:str,authorization:str|None=Header(default=None)):
    authorize(authorization)
    with database(project) as db:
        n=db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        latest=db.execute("SELECT candidate,approved,passed,total,baseline FROM evaluations ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
    return {"feedback_examples":n,"latest_evaluation":None if latest is None else
        {"candidate":latest[0],"approved":bool(latest[1]),"passed":latest[2],
         "total":latest[3],"baseline":latest[4]},
        "lifelong":lifelong.status(project),
        "gpu_training_enabled":False}
