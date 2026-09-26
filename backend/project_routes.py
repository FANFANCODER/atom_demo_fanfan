"""Project routes: CRUD, messages (SSE agent loop), files, snapshots, deployments."""
import os
import io
import json
import time
import secrets
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import (
    User, Project, Message, FileSnapshot, Deployment, get_db,
)
from auth import get_current_user
import storage
from agent import generate_site

router = APIRouter(prefix="/api/projects", tags=["projects"])

PUBLIC_BASE_URL = os.environ.get("ATOM_PUBLIC_URL", "http://localhost:8000")


def _new_slug(db: Session, name: str) -> str:
    base = re_slugify(name) or "site"
    for _ in range(50):
        candidate = f"{base}-{secrets.token_hex(3)}"
        if not db.query(Project).filter(Project.slug == candidate).first():
            return candidate
    return f"site-{secrets.token_hex(6)}"


def re_slugify(s: str) -> str:
    import re
    # strip non-ASCII for URL safety; keep a-z0-9
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:30] if s else ""


def _own_project(db: Session, user: User, project_id: str) -> Project:
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


def _project_dict(p: Project, db: Session, include_deployment: bool = True) -> dict:
    d = {
        "id": p.id, "slug": p.slug, "name": p.name,
        "template_type": p.template_type, "status": p.status,
        "public_url": p.public_url, "sandbox_state": p.sandbox_state,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if include_deployment:
        dep = db.query(Deployment).filter(Deployment.project_id == p.id).order_by(Deployment.created_at.desc()).first()
        d["latest_deployment"] = _deployment_dict(dep) if dep else None
    return d


def _deployment_dict(d: Deployment) -> dict:
    return {"id": d.id, "status": d.status, "url": d.url, "kind": d.kind,
            "created_at": d.created_at.isoformat() if d.created_at else None}


class CreateProjectIn(BaseModel):
    name: str = "Untitled"
    template_type: str = "static-html"


@router.get("")
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.user_id == user.id).order_by(Project.updated_at.desc()).all()
    return [_project_dict(p, db) for p in projects]


@router.post("")
def create_project(body: CreateProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = Project(
        id=secrets.token_urlsafe(12), user_id=user.id,
        slug=_new_slug(db, body.name), name=body.name[:80] or "Untitled",
        template_type=body.template_type, status="BUILDING",
        sandbox_state="COLD",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _project_dict(p, db)


@router.get("/{project_id}")
def get_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    data = _project_dict(p, db)
    snap = db.query(FileSnapshot).filter(FileSnapshot.project_id == p.id, FileSnapshot.is_latest == True).first()
    data["latest_snapshot"] = {"id": snap.id, "tree": snap.tree} if snap else None
    return data


@router.delete("/{project_id}")
def delete_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    # clean S3 artifacts
    for dep in db.query(Deployment).filter(Deployment.project_id == p.id).all():
        if dep.artifact_key:
            try:
                storage.delete_site(dep.artifact_key)
            except Exception:
                pass
    storage.delete_snapshots_for_project(p.id)
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.get("/{project_id}/messages")
def list_messages(project_id: str, limit: int = Query(50, ge=1, le=200),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    msgs = db.query(Message).filter(Message.project_id == p.id).order_by(Message.created_at.asc()).limit(limit).all()
    return [{"id": m.id, "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in msgs]


class SendMessageIn(BaseModel):
    content: str


@router.post("/{project_id}/messages")
async def send_message(project_id: str, body: SendMessageIn, request: Request,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    user_msg = Message(id=secrets.token_urlsafe(12), project_id=p.id, role="user", content=body.content)
    db.add(user_msg)
    db.commit()

    async def event_stream():
        # helper to send db writes in background thread safely — we use a new session per write
        from database import SessionLocal
        ldb = SessionLocal()
        try:
            yield _sse("status", "正在为你生成网站…")
            await asyncio.sleep(0.2)
            # generate the site
            result = await generate_site(body.content)
            title = result.get("title", p.name or "My Site")
            files = result["files"]
            # ensure index.html
            if "index.html" not in files:
                files["index.html"] = "<html><body>Hello</body></html>"

            yield _sse("status", f"生成完成：{title}")

            # create a deployment
            dep = Deployment(
                id=secrets.token_urlsafe(12), project_id=p.id,
                status="BUILDING", kind="static",
            )
            ldb.add(dep)
            ldb.commit()

            # store the built site
            artifact_key = storage.put_site(p.id, dep.id, files)
            url = f"{PUBLIC_BASE_URL}/sites/{p.slug}/index.html"
            dep.status = "LIVE"
            dep.artifact_key = artifact_key
            dep.url = url
            dep.duration_ms = 1200
            ldb.commit()

            p.status = "LIVE"
            p.public_url = url
            p.sandbox_state = "WARM"
            p.last_active_at = datetime.now(timezone.utc).replace(tzinfo=None)
            # merge p into ldb session so the update persists
            ldb.merge(p)
            ldb.commit()

            # save snapshot
            tree = storage.compute_tree(files)
            snap_id = secrets.token_urlsafe(12)
            storage.put_snapshot(p.id, snap_id, files)
            # mark previous latest as false
            ldb.query(FileSnapshot).filter(FileSnapshot.project_id == p.id).update({FileSnapshot.is_latest: False}, synchronize_session=False)
            snap = FileSnapshot(
                id=snap_id, project_id=p.id, tree=tree,
                storage_key=f"{p.id}/{snap_id}.tar.gz",
                size_bytes=sum(len(c) for c in files.values()),
                is_latest=True, message_id=user_msg.id,
            )
            ldb.add(snap)
            ldb.commit()

            # assistant message
            assistant_content = f"已为你生成网站：{title}\n\n预览地址：{url}\n\n包含文件：{', '.join(files.keys())}"
            amsg = Message(id=secrets.token_urlsafe(12), project_id=p.id, role="assistant", content=assistant_content)
            ldb.add(amsg)
            ldb.commit()

            yield _sse("assistant", assistant_content)
            yield _sse("deployment", {"status": "LIVE", "url": url, "id": dep.id})
            yield _sse("done", {"ok": True})
        finally:
            ldb.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(event: str, data) -> str:
    if isinstance(data, dict):
        data = json.dumps(data)
    return f"event: {event}\ndata: {data}\n\n"


@router.get("/{project_id}/files")
def list_files(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    snap = db.query(FileSnapshot).filter(FileSnapshot.project_id == p.id, FileSnapshot.is_latest == True).first()
    if not snap:
        return {"tree": {}}
    return {"tree": snap.tree}


@router.get("/{project_id}/files/{path:path}")
def get_file(project_id: str, path: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    snap = db.query(FileSnapshot).filter(FileSnapshot.project_id == p.id, FileSnapshot.is_latest == True).first()
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot")
    files = storage.get_snapshot(snap.storage_key)
    if path not in files:
        raise HTTPException(status_code=404, detail="File not found")
    content = files[path]
    ctype = "text/plain"
    if path.endswith(".html"):
        ctype = "text/html"
    elif path.endswith(".css"):
        ctype = "text/css"
    elif path.endswith(".js"):
        ctype = "application/javascript"
    elif path.endswith(".json"):
        ctype = "application/json"
    return Response(content=content, media_type=ctype)


@router.get("/{project_id}/snapshots")
def list_snapshots(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    snaps = db.query(FileSnapshot).filter(FileSnapshot.project_id == p.id).order_by(FileSnapshot.created_at.desc()).all()
    return [{"id": s.id, "is_latest": s.is_latest, "size_bytes": s.size_bytes,
             "created_at": s.created_at.isoformat() if s.created_at else None} for s in snaps]


@router.post("/{project_id}/redeploy")
def redeploy(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    snap = db.query(FileSnapshot).filter(FileSnapshot.project_id == p.id, FileSnapshot.is_latest == True).first()
    if not snap:
        raise HTTPException(status_code=400, detail="No snapshot to deploy")
    files = storage.get_snapshot(snap.storage_key)
    dep = Deployment(id=secrets.token_urlsafe(12), project_id=p.id, status="LIVE", kind="static")
    db.add(dep)
    db.commit()
    key = storage.put_site(p.id, dep.id, files)
    url = f"{PUBLIC_BASE_URL}/sites/{p.slug}/index.html"
    dep.artifact_key = key
    dep.url = url
    p.public_url = url
    p.status = "LIVE"
    db.commit()
    return {"ok": True, "url": url}
