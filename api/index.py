"""Vercel serverless entrypoint.

Vercel's Python runtime looks for an ASGI callable named `app` in this module.
Everything else lives in the `app` package so the same code runs identically
under Docker, a plain uvicorn process, or here.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The function's working directory is not guaranteed to be on sys.path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app  # noqa: E402

__all__ = ["app"]
