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

# Import the FastAPI app. Vercel detects the `app` variable as the ASGI
# entrypoint.
from main import app  # noqa: E402

# Also expose a Mangum WSGI handler as a fallback for environments that don't
# support native ASGI. Vercel will prefer the `app` ASGI variable above.
try:
    from mangum import Mangum  # noqa: E402
    handler = Mangum(app, lifespan="off")
except Exception:
    handler = None
