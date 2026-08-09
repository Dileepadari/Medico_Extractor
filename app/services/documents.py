"""Upload validation.

The client-supplied `Content-Type` is a hint, not evidence. Everything that
reaches the model is checked against its own magic bytes, and the body is read in
chunks so an oversized upload is rejected before it is fully buffered in memory.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from fastapi import UploadFile

from app.errors import (
    CorruptDocumentError,
    EmptyFileError,
    FileTooLargeError,
    UnsupportedMediaTypeError,
)

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024

# Magic-byte signatures for the formats Gemini can read as documents/images.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ValidatedDocument:
    """An upload that passed every check, ready to hand to the model."""

    content: bytes
    content_type: str
    filename: str

    @property
    def size_bytes(self) -> int:
        return len(self.content)


def sniff_content_type(head: bytes) -> str | None:
    """Detect the real media type from the first bytes of a file."""
    for signature, media_type in _SIGNATURES:
        if head.startswith(signature):
            return media_type
    # WebP: "RIFF" + 4-byte size + "WEBP".
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_filename(raw: str | None) -> str:
    """Strip path components and exotic characters before a name reaches logs."""
    if not raw:
        return "upload"
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_FILENAME.sub("_", name).strip("._") or "upload"
    return name[:128]


async def read_upload(
    upload: UploadFile,
    *,
    max_bytes: int,
    allowed_content_types: list[str],
) -> ValidatedDocument:
    """Read and validate an uploaded document.

    Raises `EmptyFileError`, `FileTooLargeError`, `UnsupportedMediaTypeError` or
    `CorruptDocumentError` - all of which map to a 4xx with a stable error code.
    """
    filename = safe_filename(upload.filename)

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FileTooLargeError(
                f"File exceeds the {_human_size(max_bytes)} limit."
            )
        chunks.append(chunk)

    if total == 0:
        raise EmptyFileError()

    content = b"".join(chunks)
    detected = sniff_content_type(content[:32])

    if detected is None:
        raise UnsupportedMediaTypeError(
            "The file is not a PDF or a supported image (JPEG, PNG, WebP)."
        )

    if detected not in allowed_content_types:
        raise UnsupportedMediaTypeError(
            f"Files of type {detected} are not accepted. "
            f"Allowed: {', '.join(allowed_content_types)}."
        )

    if detected == "application/pdf" and b"%%EOF" not in content[-2048:]:
        # Truncated fax transfers are common enough to be worth naming explicitly
        # rather than letting the model fail on an unreadable document.
        logger.warning(
            "pdf missing trailing EOF marker - possibly truncated",
            extra={"filename": filename, "size_bytes": total},
        )

    if detected == "application/pdf" and total < 100:
        raise CorruptDocumentError("The PDF is too small to contain a document.")

    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared and declared != detected and declared != "application/octet-stream":
        logger.info(
            "declared content type does not match sniffed type",
            extra={"declared": declared, "detected": detected},
        )

    return ValidatedDocument(content=content, content_type=detected, filename=filename)


def _human_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.0f} MiB"
    return f"{num_bytes / 1024:.0f} KiB"
