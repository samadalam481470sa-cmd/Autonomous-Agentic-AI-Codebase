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

@router.get("/{project}/status")
def status(project:str,authorization:str|None=Header(default=None)):
    authorize(authorization)
    with database(project) as db:
        n=db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        latest=db.execute("SELECT candidate,approved,passed,total,baseline FROM evaluations ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
    return {"feedback_examples":n,"latest_evaluation":None if latest is None else
        {"candidate":latest[0],"approved":bool(latest[1]),"passed":latest[2],
         "total":latest[3],"baseline":latest[4]},
        "gpu_training_enabled":False}
