"""Shared fixtures.

Nothing in the suite talks to Google: the extractor on `app.state` is replaced
with a stub, so tests exercise routing, validation, auth, limits and error
mapping without a network call or an API key.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import ExtractedReferralData
from app.services.documents import ValidatedDocument

# Keep a developer's real .env from leaking into the suite.
for var in ("GOOGLE_API_KEY", "API_KEY", "ENVIRONMENT", "CORS_ORIGINS"):
    os.environ.pop(var, None)


class StubExtractor:
    """Stand-in for `ReferralExtractor` with scriptable behaviour."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result if result is not None else ExtractedReferralData()
        self.error = error
        self.calls: list[ValidatedDocument] = []
        self.model_name = "stub-model"
        self.is_configured = True

    def warm_up(self) -> None:  # pragma: no cover - trivial
        return None

    async def extract(self, document: ValidatedDocument) -> ExtractedReferralData:
        self.calls.append(document)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def settings_kwargs() -> dict[str, Any]:
    """Defaults each test can override before the app is built."""
    return {
        "environment": "development",
        "google_api_key": "test-key",
        "log_format": "console",
        "log_level": "WARNING",
        "serve_frontend": False,
        "rate_limit_requests": 0,
        "_env_file": None,
    }


@pytest.fixture
def make_client(settings_kwargs):
    """Factory: build a client with custom settings and a stub extractor."""

    clients: list[TestClient] = []

    def _make(extractor: Any | None = None, **overrides: Any) -> TestClient:
        settings = Settings(**{**settings_kwargs, **overrides})
        application = create_app(settings)
        application.state.extractor = extractor or StubExtractor()

        client = TestClient(application, raise_server_exceptions=False)
        client.__enter__()  # runs lifespan
        clients.append(client)
        return client

    yield _make

    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def stub() -> StubExtractor:
    return StubExtractor()


@pytest.fixture
def pdf_bytes() -> bytes:
    """A minimal but structurally valid one-page PDF."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
        b"%%EOF\n"
    )


@pytest.fixture
def png_bytes() -> bytes:
    """A 1x1 transparent PNG."""
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"
    )


@pytest.fixture
def upload(pdf_bytes: bytes) -> Iterator[dict[str, Any]]:
    yield {"file": ("referral.pdf", pdf_bytes, "application/pdf")}
