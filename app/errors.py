"""Typed application errors and the handlers that render them.

Every failure leaving this service is shaped like `{"error": {code, message, request_id}}`
so clients can branch on `code` instead of parsing prose.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors we raise on purpose and are happy to show a client."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        if message:
            self.message = message
        super().__init__(self.message)


class UnsupportedMediaTypeError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_media_type"
    message = "Unsupported file type."


class FileTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "file_too_large"
    message = "File exceeds the configured size limit."


class EmptyFileError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "empty_file"
    message = "The uploaded file is empty."


class CorruptDocumentError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "corrupt_document"
    message = "The uploaded file could not be read as a valid document."


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"
    message = "A valid API key is required."


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests. Please retry shortly."

    def __init__(self, message: str | None = None, retry_after: int = 60) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class ModelNotConfiguredError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "model_not_configured"
    message = "Extraction is unavailable: the service has no model credentials configured."


class ModelTimeoutError(AppError):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "model_timeout"
    message = "The extraction model did not respond in time."


class ModelError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "model_error"
    message = "The extraction model failed to process this document."


def _error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id_var.get(),
            }
        },
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = None
        if isinstance(exc, RateLimitedError):
            headers = {"Retry-After": str(exc.retry_after)}
        # 5xx means *we* broke; log it loudly. 4xx is the caller's business.
        log = logger.error if exc.status_code >= 500 else logger.info
        log(
            "request failed: %s",
            exc.code,
            extra={"error_code": exc.code, "status_code": exc.status_code},
        )
        return _error_response(exc.status_code, exc.code, exc.message, headers)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            413: "file_too_large",
            415: "unsupported_media_type",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        return _error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", ())[1:]) or "request"
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            f"Invalid request: {field} - {first.get('msg', 'is invalid')}.",
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Never leak an internal traceback or message to the client; the request id
        # is the bridge between what the caller sees and what we logged.
        logger.exception("unhandled exception: %s", type(exc).__name__)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred. Quote the request id when reporting this.",
        )
