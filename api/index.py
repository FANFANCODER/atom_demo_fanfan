"""Vercel Serverless entry point for Atom backend.

Wraps the FastAPI app with Mangum so it can run on Vercel's AWS Lambda runtime.
"""
import os
import sys

# Ensure the backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from mangum import Mangum  # noqa: E402

from main import app  # noqa: E402
from database import init_db  # noqa: E402

# Make sure tables exist on first invocation (startup events may not fire in Lambda)
try:
    init_db()
except Exception as e:
    print(f"[vercel] init_db warning: {e}")

handler = Mangum(app, lifespan="off")
