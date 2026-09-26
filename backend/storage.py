"""File storage abstraction.

Two backends:
- Local filesystem (default, for local dev): stores tar.gz snapshots and site files on disk.
- Vercel Blob (when BLOB_READ_WRITE_TOKEN is set): stores blobs via the Blob REST API.

The interface is identical so the rest of the app does not care which backend is used.
"""
import os
import io
import json
import tarfile
import hashlib
import httpx
from pathlib import Path

# ---- Backend selection ----
BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
USE_BLOB = bool(BLOB_TOKEN)

# Local storage root. On Vercel Serverless the filesystem is read-only except
# /tmp, so when using Blob we don't need local dirs at all.
STORAGE_ROOT = os.environ.get(
    "ATOM_STORAGE_ROOT",
    "/tmp/atom-storage" if USE_BLOB else os.path.join(os.path.dirname(__file__), "storage"),
)
SNAPSHOTS_DIR = os.path.join(STORAGE_ROOT, "snapshots")
SITES_DIR = os.path.join(STORAGE_ROOT, "sites")
LOGS_DIR = os.path.join(STORAGE_ROOT, "logs")

if not USE_BLOB:
    for d in (SNAPSHOTS_DIR, SITES_DIR, LOGS_DIR):
        os.makedirs(d, exist_ok=True)


# ---------- helpers ----------
def _safe_path(base: str, key: str) -> str:
    full = os.path.normpath(os.path.join(base, key))
    base_abs = os.path.abspath(base)
    if not os.path.abspath(full).startswith(base_abs):
        raise ValueError("Unsafe path")
    return full


def _tar_files(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _untar_bytes(data: bytes) -> dict:
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if member.name.startswith("/") or ".." in member.name:
                continue
            f = tar.extractfile(member)
            if f:
                files[member.name] = f.read()
    return files


# ---------- Vercel Blob backend ----------
def _blob_put(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload a blob, return its public URL."""
    # Vercel Blob multipart upload
    boundary = "----atomblob" + os.urandom(8).hex()
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(key)}"\r\n'.encode())
    body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.write(data)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    raw = body.getvalue()

    r = httpx.post(
        "https://blob.vercel-storage.com/upload",
        headers={
            "Authorization": f"Bearer {BLOB_TOKEN}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        params={"path": key, "addRandomSuffix": "false"},
        content=raw,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["url"]


def _blob_get(url: str) -> bytes:
    r = httpx.get(url, timeout=60)
    r.raise_for_status()
    return r.content


def _blob_delete(url: str):
    try:
        httpx.post(
            "https://blob.vercel-storage.com/delete",
            headers={"Authorization": f"Bearer {BLOB_TOKEN}"},
            json={"urls": [url]},
            timeout=30,
        )
    except Exception:
        pass


def _blob_list(prefix: str):
    """List blob URLs under a prefix. Returns a list of URLs."""
    urls = []
    cursor = None
    while True:
        params = {"prefix": prefix, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        r = httpx.get(
            "https://blob.vercel-storage.com",
            headers={"Authorization": f"Bearer {BLOB_TOKEN}"},
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        urls.extend(b["url"] for b in data.get("blobs", []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return urls


# ---------- public API ----------
def put_snapshot(project_id: str, snapshot_id: str, files: dict) -> str:
    """files: {path: content_bytes}. Returns storage_key."""
    data = _tar_files(files)
    key = f"snapshots/{project_id}/{snapshot_id}.tar.gz"
    if USE_BLOB:
        url = _blob_put(key, data, "application/gzip")
        return url  # store the blob URL as the key
    full = _safe_path(SNAPSHOTS_DIR, f"{project_id}/{snapshot_id}.tar.gz")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)
    return f"{project_id}/{snapshot_id}.tar.gz"


def get_snapshot(storage_key: str) -> dict:
    """Returns {path: content_bytes} from a stored tar.gz."""
    if USE_BLOB:
        data = _blob_get(storage_key)
        return _untar_bytes(data)
    full = _safe_path(SNAPSHOTS_DIR, storage_key)
    if not os.path.exists(full):
        return {}
    with open(full, "rb") as f:
        return _untar_bytes(f.read())


def put_site(project_id: str, deployment_id: str, files: dict) -> str:
    """Store a built static site. Returns artifact_key."""
    if USE_BLOB:
        # store the whole site as a tar.gz blob; serve_site_file extracts on demand
        data = _tar_files(files)
        key = f"sites/{project_id}/{deployment_id}.tar.gz"
        url = _blob_put(key, data, "application/gzip")
        return url
    key = f"{project_id}/{deployment_id}"
    base = _safe_path(SITES_DIR, key)
    os.makedirs(base, exist_ok=True)
    for path, content in files.items():
        if path.startswith("/") or ".." in path:
            continue
        full = os.path.join(base, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(content if isinstance(content, bytes) else content.encode("utf-8"))
    return key


def get_site_file(artifact_key: str, rel_path: str):
    """Return content_bytes for a deployed site file, or None."""
    if USE_BLOB:
        data = _blob_get(artifact_key)
        files = _untar_bytes(data)
        content = files.get(rel_path)
        if content is None and rel_path != "index.html":
            content = files.get("index.html")
        return content
    base = _safe_path(SITES_DIR, artifact_key)
    full = _safe_path(base, rel_path)
    if not os.path.exists(full) or not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        return f.read()


def site_dir(artifact_key: str) -> str:
    return _safe_path(SITES_DIR, artifact_key)


def delete_site(artifact_key: str):
    if USE_BLOB:
        _blob_delete(artifact_key)
        return
    import shutil
    base = _safe_path(SITES_DIR, artifact_key)
    if os.path.exists(base):
        shutil.rmtree(base, ignore_errors=True)


def delete_snapshots_for_project(project_id: str):
    if USE_BLOB:
        for url in _blob_list(f"snapshots/{project_id}/"):
            _blob_delete(url)
        return
    import shutil
    base = _safe_path(SNAPSHOTS_DIR, project_id)
    if os.path.exists(base):
        shutil.rmtree(base, ignore_errors=True)


def compute_tree(files: dict) -> dict:
    return {p: hashlib.sha256(c if isinstance(c, bytes) else c.encode()).hexdigest() for p, c in files.items()}
