"""Vercel Serverless entry point for Atom backend.

Exposes the FastAPI ASGI app so Vercel's Python runtime can detect and run it.
"""
import os
import sys
import signal

# Ensure the backend package is importable
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


class _TimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _TimeoutError("init_db timed out")


# Initialize database tables with a timeout so a slow/unreachable DB doesn't
# hang the cold start. Vercel serverless functions have limited time.
try:
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(8)  # 8 second timeout
    from database import init_db  # noqa: E402
    init_db()
    signal.alarm(0)  # cancel timeout
    print("[vercel] init_db OK")
except _TimeoutError:
    print("[vercel] init_db timed out (DB unreachable?), continuing")
except Exception as e:
    print(f"[vercel] init_db warning: {e}")
finally:
    try:
        signal.alarm(0)
    except Exception:
        pass

# Import the FastAPI app.
# Vercel's native ASGI runtime has a known issue where request bodies are not
# passed to the ASGI app (resulting in 422 "Field required" / body=null).
# Wrapping the app with Mangum converts it to a WSGI callable; Vercel then
# uses its WSGI handler which correctly forwards the request body.
from main import app as _asgi_app  # noqa: E402

try:
    from mangum import Mangum  # noqa: E402
    # Expose the Mangum WSGI handler as `app` so Vercel uses the WSGI path.
    app = Mangum(_asgi_app, lifespan="off")
except Exception as e:
    print(f"[vercel] Mangum unavailable ({e}); falling back to raw ASGI")
    app = _asgi_app
