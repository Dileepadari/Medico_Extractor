"""The extraction endpoint."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.config import Settings
from app.dependencies import get_app_settings, get_extractor
from app.logging_config import request_id_var
from app.schemas import (
    ErrorResponse,
    ExtractionMeta,
    ExtractionResponse,
)
from app.security import enforce_rate_limit, verify_api_key
from app.services.documents import read_upload
from app.services.extractor import ReferralExtractor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extraction"])

_ERROR_RESPONSES: dict[int | str, dict] = {
    400: {"model": ErrorResponse, "description": "The upload was empty."},
    401: {"model": ErrorResponse, "description": "Missing or invalid API key."},
    413: {"model": ErrorResponse, "description": "File exceeds the size limit."},
    415: {"model": ErrorResponse, "description": "Unsupported file type."},
    422: {"model": ErrorResponse, "description": "The document could not be read."},
    429: {"model": ErrorResponse, "description": "Rate limit exceeded."},
    502: {"model": ErrorResponse, "description": "The model call failed."},
    503: {"model": ErrorResponse, "description": "No model credentials configured."},
    504: {"model": ErrorResponse, "description": "The model call timed out."},
}


@router.post(
    "/extract",
    response_model=ExtractionResponse,
    responses=_ERROR_RESPONSES,
    summary="Extract structured data from a referral document",
    dependencies=[Depends(verify_api_key), Depends(enforce_rate_limit)],
)
async def extract(
    request: Request,
    file: UploadFile = File(..., description="A referral PDF or scanned image."),
    settings: Settings = Depends(get_app_settings),
    extractor: ReferralExtractor = Depends(get_extractor),
) -> ExtractionResponse:
    """Upload one referral document and get back the structured fields it contains.

    Fields that are absent from the document come back as empty strings - the
    model is instructed never to guess. No part of the document is written to
    disk or logged; it lives in memory for the duration of the request only.
    """
    started = time.perf_counter()

    document = await read_upload(
        file,
        max_bytes=settings.max_upload_bytes,
        allowed_content_types=settings.allowed_content_types,
    )

    logger.info(
        "extraction requested",
        extra={
            "filename": document.filename,
            "content_type": document.content_type,
            "size_bytes": document.size_bytes,
        },
    )

    data = await extractor.extract(document)

    return ExtractionResponse(
        data=data,
        meta=ExtractionMeta(
            request_id=request_id_var.get() or getattr(request.state, "request_id", ""),
            filename=document.filename,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            model=extractor.model_name,
            duration_ms=int((time.perf_counter() - started) * 1000),
        ),
    )
