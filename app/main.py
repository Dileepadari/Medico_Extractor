"""Application factory and ASGI entrypoint.

Run locally with:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import Settings, get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.routers import extraction, health
from app.security import SlidingWindowRateLimiter
from app.services.extractor import ReferralExtractor

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

API_PREFIX = "/api/v1"

DESCRIPTION = """
Extract structured patient, insurance and referral fields from medical referral
documents - native PDFs and scanned faxes alike - using Gemini's multimodal
understanding with a strictly typed output schema.

* `POST /api/v1/extract` - upload a document, get structured JSON back.
* `GET /healthz` - liveness. `GET /readyz` - readiness.

Uploaded documents are held in memory for the duration of the request and are
never written to disk or logged.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings

    for warning in settings.startup_warnings():
        logger.warning(warning)

    # Build the model client up front so the first user request isn't the one
    # that pays for client construction (and so a bad key surfaces at boot).
    try:
        app.state.extractor.warm_up()
    except Exception:
        logger.exception("failed to initialise the extraction model client")

    logger.info(
        "service started",
        extra={
            "version": __version__,
            "environment": settings.environment,
            "model": settings.gemini_model,
            "model_configured": settings.model_configured,
        },
    )
    yield
    logger.info("service stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application. Accepts settings so tests can inject their own."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="Medico Extractor",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        root_path=settings.root_path,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        contact={"name": "Dileep Adari", "url": "https://dileepadari.dev"},
        license_info={"name": "MIT"},
    )

    # Request-scoped collaborators live on app.state, not in module globals, so
    # several apps (tests, embedded use) can coexist in one process.
    app.state.settings = settings
    app.state.extractor = ReferralExtractor(settings)
    app.state.rate_limiter = SlidingWindowRateLimiter(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )

    # Middleware runs bottom-up: request context wraps everything, so the request
    # id is set before CORS or security headers touch the response.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=settings.is_production)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(extraction.router, prefix=API_PREFIX)
    # Unversioned alias kept for the original clients that call POST /extract.
    app.include_router(extraction.router, include_in_schema=False)

    _mount_frontend(app, settings)

    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the bundled single-page UI, if it exists and is enabled."""
    index_file = STATIC_DIR / "index.html"

    if not settings.serve_frontend or not index_file.exists():
        @app.get("/", include_in_schema=False)
        async def _api_root() -> JSONResponse:
            return JSONResponse(
                {
                    "service": "medico-extractor",
                    "version": __version__,
                    "docs": "/docs" if settings.docs_enabled else None,
                    "extract": f"{API_PREFIX}/extract",
                }
            )

        return

    app.mount(
        "/static", StaticFiles(directory=str(STATIC_DIR)), name="static"
    )

    @app.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(index_file, headers={"Cache-Control": "no-store"})

    favicon = STATIC_DIR / "favicon.png"
    if favicon.exists():
        @app.get("/favicon.ico", include_in_schema=False)
        async def _favicon() -> FileResponse:
            return FileResponse(
                favicon,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"},
            )


app = create_app()
