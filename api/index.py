"""Vercel Serverless entry point for Atom backend.

With pyproject.toml specifying `entrypoint = "backend.main:app"`, Vercel's
FastAPI framework support uses the app directly. This file is kept as a
fallback for environments that look for an `api/index.py` entrypoint.
"""
import os
import sys

_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from main import app  # noqa: E402
