"""Atom backend entrypoint: FastAPI app with auth, projects, static sites, and frontend."""
import os
import sys
import time
import signal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, SessionLocal, Project, Deployment, SiteFile, engine, DB_URL
import auth_routes, project_routes
import storage

app = FastAPI(title="Atom", version="0.4.0")

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(project_routes.router)

BASE_DIR = Path(__file__).resolve().parent


class _InitTimeoutError(Exception):
    pass


def _init_timeout_handler(signum, frame):
    raise _InitTimeoutError("init_db timed out")


def _safe_init_db(max_wait: float = 25.0) -> bool:
    """Initialize the DB with retries. Returns True on success.

    Neon Postgres cold start can take several seconds. We retry init_db
    for up to ``max_wait`` seconds so the site_files table is reliably
    created even on a cold start.
    """
    deadline = time.monotonic() + max_wait
    attempt = 0
    while True:
        attempt += 1
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            per_attempt = min(10, int(remaining))
            signal.signal(signal.SIGALRM, _init_timeout_handler)
            signal.alarm(per_attempt)
            init_db()
            signal.alarm(0)
            print(f"[atom] DB initialized on attempt {attempt}")
            return True
        except _InitTimeoutError:
            signal.alarm(0)
            print(f"[atom] init_db attempt {attempt} timed out, retrying…")
            time.sleep(1)
        except Exception as e:
            signal.alarm(0)
            print(f"[atom] init_db attempt {attempt} error: {e}")
            time.sleep(1)
        if time.monotonic() >= deadline:
            break
    print("[atom] init_db failed after retries; continuing without DB init")
    return False


@app.on_event("startup")
def startup():
    _safe_init_db()


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.4.0"}


@app.get("/api/storage-info")
def storage_info():
    """Diagnostic endpoint: report which storage backend is active and
    whether the site_files table exists (so generated sites persist)."""
    info = {
        "db_scheme": "sqlite" if DB_URL.startswith("sqlite") else "postgres",
        "db_persistent": not DB_URL.startswith("sqlite"),
        "blob_enabled": storage.USE_BLOB,
        "site_files_table_exists": False,
        "site_file_count": 0,
        "deployment_count": 0,
    }
    db = SessionLocal()
    try:
        from sqlalchemy import inspect, func
        insp = inspect(engine)
        info["site_files_table_exists"] = insp.has_table("site_files")
        if info["site_files_table_exists"]:
            info["site_file_count"] = db.query(func.count(SiteFile.id)).scalar() or 0
        info["deployment_count"] = db.query(func.count(Deployment.id)).scalar() or 0
        db_dep = db.query(Deployment).filter(Deployment.artifact_key.like("db:%")).first()
        info["db_artifact_used"] = db_dep is not None
    except Exception as e:
        info["error"] = str(e)
    finally:
        db.close()
    return info


# ---------- Deployed static sites ----------
def _serve_site_file(slug: str, path: str):
    db = SessionLocal()
    try:
        p = db.query(Project).filter(Project.slug == slug).first()
        if not p:
            return JSONResponse(status_code=404, content={"error": "Site not found"})
        dep = db.query(Deployment).filter(Deployment.project_id == p.id, Deployment.status == "LIVE")\
            .order_by(Deployment.created_at.desc()).first()
        if not dep or not dep.artifact_key:
            return JSONResponse(status_code=404, content={"error": "No live deployment"})
        rel = path or "index.html"
        content = storage.get_site_file(dep.artifact_key, rel)
        if content is None:
            content = storage.get_site_file(dep.artifact_key, "index.html")
            rel = "index.html"
        if content is None:
            return JSONResponse(status_code=404, content={"error": "Not found"})
        ctype = _content_type(rel)
        from fastapi import Response
        return Response(content=content, media_type=ctype)
    finally:
        db.close()


@app.get("/sites/{slug}/{path:path}")
def serve_site(slug: str, path: str):
    return _serve_site_file(slug, path)


@app.get("/sites/{slug}")
def serve_site_root(slug: str):
    return RedirectResponse(url=f"/sites/{slug}/index.html")


@app.get("/api/sites/{slug}/{path:path}")
def serve_site_via_api(slug: str, path: str):
    return _serve_site_file(slug, path)


@app.get("/api/sites/{slug}")
def serve_site_root_via_api(slug: str):
    return RedirectResponse(url=f"/api/sites/{slug}/index.html")


def _content_type(path: str) -> str:
    if path.endswith(".html"):
        return "text/html; charset=utf-8"
    if path.endswith(".css"):
        return "text/css; charset=utf-8"
    if path.endswith(".js") or path.endswith(".mjs"):
        return "application/javascript; charset=utf-8"
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".svg"):
        return "image/svg+xml"
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".jpg") or path.endswith(".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


# ---------- Frontend SPA fallback ----------
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
if FRONTEND_DIST.exists() and FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse(status_code=404, content={"error": "Frontend not built"})
else:
    @app.get("/")
    def root():
        return JSONResponse({"message": "Atom API running. Build frontend to serve UI.",
                             "docs": "/docs"})


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
