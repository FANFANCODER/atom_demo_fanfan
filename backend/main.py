"""Atom backend entrypoint: FastAPI app with auth, projects, static sites, and frontend."""
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, SessionLocal, Project, Deployment
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


@app.on_event("startup")
def startup():
    try:
        init_db()
        print("[atom] DB initialized")
    except Exception as e:
        print(f"[atom] init_db error: {e}")


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.4.0"}


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
            # fallback to index.html for SPA routing
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


# Vercel: /sites/* is rewritten to /api/sites/* so it reaches the serverless fn
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
# On Vercel, static files are served by Vercel CDN; only /api/* and /sites/*
# reach this FastAPI app. The SPA fallback only matters for local dev.
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
if FRONTEND_DIST.exists() and FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # API and sites handled above; serve index.html for everything else
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
