"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app import __version__
from app.config import Settings
from app.dependencies import get_app_settings
from app.schemas import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz(settings: Settings = Depends(get_app_settings)) -> HealthResponse:
    """Always 200 while the process is running. Safe for load-balancer checks."""
    return HealthResponse(
        status="ok", version=__version__, environment=settings.environment
    )


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz(
    response: Response, settings: Settings = Depends(get_app_settings)
) -> ReadinessResponse:
    """503 unless the service can actually serve an extraction request.

    Keeping this separate from `/healthz` means a missing API key takes the
    instance out of rotation instead of restarting it in a loop.
    """
    checks = {
        "model_credentials": "ok" if settings.model_configured else "missing",
    }
    ready = all(value == "ok" for value in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        version=__version__,
        environment=settings.environment,
        checks=checks,
    )
