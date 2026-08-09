"""Cross-cutting HTTP middleware: request ids, access logs, security headers."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_var

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"

# Paths that would otherwise fill the logs with noise.
_QUIET_PATHS = frozenset({"/healthz", "/readyz", "/favicon.ico"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns each request an id, echoes it back, and emits one access log line."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Honour an upstream id (load balancer, gateway) so traces stitch together.
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming[:64] if incoming else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        # The contextvar is reset only after the access log is written, so every
        # line belonging to this request - the last one included - carries its id.
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "%s %s -> unhandled",
                    request.method,
                    request.url.path,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": int((time.perf_counter() - started) * 1000),
                        "client_ip": client_ip(request),
                    },
                )
                raise

            duration_ms = int((time.perf_counter() - started) * 1000)
            response.headers[REQUEST_ID_HEADER] = request_id

            if request.url.path not in _QUIET_PATHS:
                logger.info(
                    "%s %s -> %s",
                    request.method,
                    request.url.path,
                    response.status_code,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                        "client_ip": client_ip(request),
                    },
                )
            return response
        finally:
            request_id_var.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers for both the API and the bundled frontend."""

    def __init__(self, app, *, enable_hsts: bool = False) -> None:
        super().__init__(app)
        self.enable_hsts = enable_hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # Uploaded documents contain PHI - keep them out of shared caches.
        headers.setdefault("Cache-Control", "no-store")
        if self.enable_hsts:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def client_ip(request: Request) -> str:
    """Best-effort client IP.

    Trusts `X-Forwarded-For` because this service is expected to sit behind a
    reverse proxy or platform edge. Used only for rate limiting and logs, never
    for authorization.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"
