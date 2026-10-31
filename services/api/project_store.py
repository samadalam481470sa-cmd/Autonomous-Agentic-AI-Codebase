"""Versioned, transactional local project and task store.

SQLite is for single-user desktop mode. Multi-user deployments require a
separate Postgres-backed service with tenant isolation and authentication.
"""
import os
import sqlite3
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from .studio import authorize

router=APIRouter(prefix="/api/projects",tags=["projects"])
def connect():
    path=Path(os.getenv("PROJECT_DB_PATH",str(Path.home()/".agentic-ai"/"projects.sqlite3")))
    path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,timeout=15)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS projects(
      id TEXT PRIMARY KEY,slug TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS tasks(
      id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      kind TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled')),
      payload TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id,status,created_at);
    CREATE TABLE IF NOT EXISTS artifacts(
      id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      path TEXT NOT NULL,sha256 TEXT NOT NULL,created_at INTEGER NOT NULL,
      UNIQUE(project_id,path,sha256));
    CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      event_type TEXT NOT NULL,details TEXT NOT NULL,created_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_events_project_time ON events(project_id,created_at,id);
    """)
    return con

class NewProject(BaseModel):
    slug:str=Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    title:str=Field(min_length=1,max_length=160)

@router.post("")
def create(body:NewProject,authorization:str|None=Header(default=None)):
    authorize(authorization)
    now=int(time.time())
    id=str(uuid.uuid4())
    with connect() as con:
        try:
            con.execute("INSERT INTO projects VALUES(?,?,?,?,?)",(id,body.slug,body.title,now,now))
            con.execute("INSERT INTO events(project_id,event_type,details,created_at) VALUES(?,?,?,?)",(id,"project.created","{}",now))
        except sqlite3.IntegrityError:raise HTTPException(409,"Project slug already exists")
    return {"id":id,"slug":body.slug,"title":body.title}

@router.get("")
def list_projects(authorization:str|None=Header(default=None)):
    authorize(authorization)
    with connect() as con:
        return {"projects":[dict(x) for x in con.execute("SELECT id,slug,title,created_at,updated_at FROM projects ORDER BY updated_at DESC LIMIT 200")]}
