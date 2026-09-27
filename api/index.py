"""Vercel Serverless entry point for Atom backend.

Exposes the FastAPI app so Vercel's Python runtime can detect the ASGI
entrypoint. The app is imported from the backend package.
"""
import os
import sys

# Ensure the backend package is importable
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from main import app as _fastapi_app  # noqa: E402
from database import init_db  # noqa: E402

# Re-export as a direct assignment so Vercel's FastAPI entrypoint detector
# can find the ASGI app in this default-location file.
app = _fastapi_app

# Make sure tables exist on first invocation (startup events may not fire in Lambda)
try:
    init_db()
except Exception as e:
    print(f"[vercel] init_db warning: {e}")

# Mangum handler for WSGI-style invocation (kept for compatibility; Vercel
# can also run the ASGI `app` above directly).
from mangum import Mangum  # noqa: E402
handler = Mangum(app, lifespan="off")
