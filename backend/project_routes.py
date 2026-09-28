import os
import io
import json
import time
import secrets
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Body
from fastapi.responses import StreamingResponse, Response
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from database import (
    User, Project, Message, FileSnapshot, Deployment, get_db,
)
from auth import get_current_user
import storage
from agent import generate_site_stream

router = APIRouter(prefix="/api/projects", tags=["projects"])

PUBLIC_BASE_URL = os.environ.get("ATOM_PUBLIC_URL", "")


def get_base_url(request: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return ""


def _new_slug(db: Session, name: str) -> str:
    base = re_slugify(name) or "site"
    for _ in range(50):
        candidate = f"{base}-{secrets.token_hex(3)}"
        if not db.query(Project).filter(Project.slug == candidate).first():
            return candidate
    return f"site-{secrets.token_hex(6)}"


def re_slugify(s: str) -> str:
    import re
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
def create_project(body: Optional[CreateProjectIn] = Body(default=None),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (body.name if body else None) or "Untitled"
    template_type = (body.template_type if body else None) or "static-html"
    p = Project(
        id=secrets.token_urlsafe(12), user_id=user.id,
        slug=_new_slug(db, name), name=name[:80] or "Untitled",
        template_type=template_type, status="BUILDING",
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
    # 对话任务提前入库：用户消息 + assistant 占位消息（content 为空表示
    # "生成中"）。这样刷新页面 / SSE 断开后，历史记录依然完整可查。
    user_msg = Message(id=secrets.token_urlsafe(12), project_id=p.id, role="user", content=body.content)
    db.add(user_msg)
    db.commit()
    assistant_msg = Message(id=secrets.token_urlsafe(12), project_id=p.id, role="assistant", content="")
    db.add(assistant_msg)
    db.commit()
    project_id_safe = p.id
    project_slug = p.slug
    project_name = p.name
    user_msg_id = user_msg.id
    assistant_msg_id = assistant_msg.id
    db.close()

    queue: asyncio.Queue = asyncio.Queue()

    async def run_generation():
        """完整生成 + 入库，与 SSE 连接解耦：客户端断开也不影响执行。"""
        from database import SessionLocal
        ldb = SessionLocal()
        try:
            await queue.put(("status", "正在为你生成网站…"))

            result = None
            async for evt in generate_site_stream(body.content):
                etype = evt.get("type")
                if etype == "llm_status":
                    await queue.put(("status", evt.get("message", "")))
                elif etype == "llm_reasoning":
                    await queue.put(("llm_reasoning", evt.get("content", "")))
                elif etype == "llm_error":
                    await queue.put(("llm_error", evt.get("error", "")))
                elif etype == "done":
                    result = evt.get("data")
                    break

            if not result:
                err = "生成失败：未获得有效结果"
                am = ldb.query(Message).filter(Message.id == assistant_msg_id).first()
                if am is not None:
                    am.content = err
                    ldb.commit()
                await queue.put(("error", err))
                return

            title = result.get("title", project_name or "My Site")
            files = result["files"]
            if "index.html" not in files:
                files["index.html"] = "<html><body>Hello</body></html>"

            await queue.put(("status", f"生成完成：{title}"))

            dep = Deployment(
                id=secrets.token_urlsafe(12), project_id=project_id_safe,
                status="BUILDING", kind="static",
            )
            ldb.add(dep)
            ldb.commit()

            artifact_key = storage.put_site(project_id_safe, dep.id, files)
            base_url = get_base_url(request)
            url = f"{base_url}/sites/{project_slug}/index.html"
            dep.status = "LIVE"
            dep.artifact_key = artifact_key
            dep.url = url
            dep.duration_ms = 1200
            ldb.commit()

            proj = ldb.query(Project).filter(Project.id == project_id_safe).first()
            if proj:
                proj.status = "LIVE"
                proj.public_url = url
                proj.sandbox_state = "WARM"
                proj.last_active_at = datetime.now(timezone.utc).replace(tzinfo=None)
                ldb.commit()

            tree = storage.compute_tree(files)
            snap_id = secrets.token_urlsafe(12)
            storage.put_snapshot(project_id_safe, snap_id, files)
            ldb.query(FileSnapshot).filter(FileSnapshot.project_id == project_id_safe).update(
                {FileSnapshot.is_latest: False}, synchronize_session=False)
            snap = FileSnapshot(
                id=snap_id, project_id=project_id_safe, tree=tree,
                storage_key=f"{project_id_safe}/{snap_id}.tar.gz",
                size_bytes=sum(len(c) for c in files.values()),
                is_latest=True, message_id=user_msg_id,
            )
            ldb.add(snap)
            ldb.commit()

            assistant_content = f"已为你生成网站：{title}\n\n预览地址：{url}\n\n包含文件：{', '.join(files.keys())}"
            am = ldb.query(Message).filter(Message.id == assistant_msg_id).first()
            if am is not None:
                am.content = assistant_content
                ldb.commit()

            await queue.put(("assistant", assistant_content))
            await queue.put(("deployment", {"status": "LIVE", "url": url, "id": dep.id}))
            await queue.put(("done", {"ok": True}))
        except Exception as e:
            print(f"[send_message] generation error: {e}")
            import traceback
            traceback.print_exc()
            try:
                am = ldb.query(Message).filter(Message.id == assistant_msg_id).first()
                if am is not None and not am.content:
                    am.content = f"生成失败：{e}"
                    ldb.commit()
            except Exception:
                pass
            await queue.put(("error", str(e)))
        finally:
            await queue.put(("__end__", None))
            ldb.close()

    gen_task = asyncio.create_task(run_generation())

    async def event_stream():
        # 只负责把生成进度转发给客户端；断开后 run_generation 照常执行。
        while True:
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": ping\n\n"  # 心跳，防止中间层空闲超时
                continue
            etype, data = evt
            if etype == "__end__":
                break
            yield _sse(etype, data)

    async def finish_generation():
        # BackgroundTask 在响应结束后执行（serverless 冻结前）：
        # 即使客户端已断开，也等生成任务跑完并入库。
        try:
            await gen_task
        except Exception:
            pass

    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        background=BackgroundTask(finish_generation),
    )


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
def redeploy(project_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _own_project(db, user, project_id)
    snap = db.query(FileSnapshot).filter(FileSnapshot.project_id == p.id, FileSnapshot.is_latest == True).first()
    if not snap:
        raise HTTPException(status_code=400, detail="No snapshot to deploy")
    files = storage.get_snapshot(snap.storage_key)
    dep = Deployment(id=secrets.token_urlsafe(12), project_id=p.id, status="LIVE", kind="static")
    db.add(dep)
    db.commit()
    key = storage.put_site(p.id, dep.id, files)
    base_url = get_base_url(request)
    url = f"{base_url}/sites/{p.slug}/index.html"
    dep.artifact_key = key
    dep.url = url
    p.public_url = url
    p.status = "LIVE"
    db.commit()
    return {"ok": True, "url": url}
