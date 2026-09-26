"""File storage abstraction. Uses local filesystem (S3-compatible interface)."""
import os
import io
import tarfile
import hashlib
from pathlib import Path

STORAGE_ROOT = os.environ.get("ATOM_STORAGE_ROOT", os.path.join(os.path.dirname(__file__), "storage"))
SNAPSHOTS_DIR = os.path.join(STORAGE_ROOT, "snapshots")
SITES_DIR = os.path.join(STORAGE_ROOT, "sites")
LOGS_DIR = os.path.join(STORAGE_ROOT, "logs")

for d in (SNAPSHOTS_DIR, SITES_DIR, LOGS_DIR):
    os.makedirs(d, exist_ok=True)


def _safe_path(base: str, key: str) -> str:
    """Prevent path traversal."""
    full = os.path.normpath(os.path.join(base, key))
    base_abs = os.path.abspath(base)
    if not os.path.abspath(full).startswith(base_abs):
        raise ValueError("Unsafe path")
    return full


def put_snapshot(project_id: str, snapshot_id: str, files: dict) -> str:
    """files: {path: content_bytes}. Returns storage_key."""
    key = f"{project_id}/{snapshot_id}.tar.gz"
    full = _safe_path(SNAPSHOTS_DIR, key)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    with open(full, "wb") as f:
        f.write(buf.getvalue())
    return key


def get_snapshot(storage_key: str) -> dict:
    """Returns {path: content_bytes} from a stored tar.gz."""
    full = _safe_path(SNAPSHOTS_DIR, storage_key)
    files = {}
    if not os.path.exists(full):
        return files
    with tarfile.open(full, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if member.name.startswith("/") or ".." in member.name:
                continue
            f = tar.extractfile(member)
            if f:
                files[member.name] = f.read()
    return files


def put_site(project_id: str, deployment_id: str, files: dict) -> str:
    """Store a built static site. Returns artifact_key."""
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
    """Return (content_bytes, content_type) for a deployed site file, or None."""
    base = _safe_path(SITES_DIR, artifact_key)
    full = _safe_path(base, rel_path)
    if not os.path.exists(full) or not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        return f.read()


def site_dir(artifact_key: str) -> str:
    return _safe_path(SITES_DIR, artifact_key)


def delete_site(artifact_key: str):
    import shutil
    base = _safe_path(SITES_DIR, artifact_key)
    if os.path.exists(base):
        shutil.rmtree(base, ignore_errors=True)


def delete_snapshots_for_project(project_id: str):
    import shutil
    base = _safe_path(SNAPSHOTS_DIR, project_id)
    if os.path.exists(base):
        shutil.rmtree(base, ignore_errors=True)


def compute_tree(files: dict) -> dict:
    return {p: hashlib.sha256(c if isinstance(c, bytes) else c.encode()).hexdigest() for p, c in files.items()}
