"""Shared FastAPI dependencies.

Everything a request needs is read off `app.state`, which `create_app` populates.
That keeps request handling free of module-level globals and lets tests build an
app with any settings they like.
"""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.security import SlidingWindowRateLimiter
from app.services.extractor import ReferralExtractor


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_extractor(request: Request) -> ReferralExtractor:
    """The single extractor instance created when the app was built."""
    return request.app.state.extractor


def get_rate_limiter(request: Request) -> SlidingWindowRateLimiter:
    return request.app.state.rate_limiter
