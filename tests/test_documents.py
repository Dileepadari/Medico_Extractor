"""Upload validation: content sniffing, size limits, filename hygiene."""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile

from app.errors import (
    EmptyFileError,
    FileTooLargeError,
    UnsupportedMediaTypeError,
)
from app.services.documents import read_upload, safe_filename, sniff_content_type

ALLOWED = ["application/pdf", "image/jpeg", "image/png", "image/webp"]


def _upload(content: bytes, filename: str = "x.pdf", content_type: str = "application/pdf"):
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers={"content-type": content_type},  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"%PDF-1.7\n...", "application/pdf"),
        (b"\xff\xd8\xff\xe0JFIF", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"GIF89a", "image/gif"),
        (b"not a document at all", None),
    ],
)
def test_sniff_content_type(head, expected):
    assert sniff_content_type(head) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("referral.pdf", "referral.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\scan 01.pdf", "scan_01.pdf"),
        ("", "upload"),
        (None, "upload"),
        ("...", "upload"),
    ],
)
def test_safe_filename_strips_paths_and_oddities(raw, expected):
    assert safe_filename(raw) == expected


def test_safe_filename_is_bounded():
    assert len(safe_filename("a" * 500 + ".pdf")) <= 128


async def test_accepts_a_valid_pdf(pdf_bytes):
    document = await read_upload(
        _upload(pdf_bytes), max_bytes=1024 * 1024, allowed_content_types=ALLOWED
    )

    assert document.content_type == "application/pdf"
    assert document.size_bytes == len(pdf_bytes)
    assert document.filename == "x.pdf"


async def test_rejects_an_empty_upload():
    with pytest.raises(EmptyFileError):
        await read_upload(_upload(b""), max_bytes=1024, allowed_content_types=ALLOWED)


async def test_rejects_an_oversized_upload(pdf_bytes):
    padded = pdf_bytes + b"0" * 5000

    with pytest.raises(FileTooLargeError):
        await read_upload(_upload(padded), max_bytes=1024, allowed_content_types=ALLOWED)


async def test_rejects_a_file_whose_bytes_are_not_a_document():
    with pytest.raises(UnsupportedMediaTypeError):
        await read_upload(
            _upload(b"#!/bin/sh\nrm -rf /\n", filename="evil.pdf"),
            max_bytes=1024 * 1024,
            allowed_content_types=ALLOWED,
        )


async def test_rejects_a_real_format_that_is_not_allowed(png_bytes):
    """A PNG is a valid image but must still be refused if it is not configured."""
    with pytest.raises(UnsupportedMediaTypeError):
        await read_upload(
            _upload(png_bytes, filename="scan.png", content_type="image/png"),
            max_bytes=1024 * 1024,
            allowed_content_types=["application/pdf"],
        )


async def test_declared_content_type_cannot_smuggle_a_payload(png_bytes):
    """A PNG claiming to be a PDF is classified by its bytes, not its header."""
    document = await read_upload(
        _upload(png_bytes, filename="fake.pdf", content_type="application/pdf"),
        max_bytes=1024 * 1024,
        allowed_content_types=ALLOWED,
    )

    assert document.content_type == "image/png"
