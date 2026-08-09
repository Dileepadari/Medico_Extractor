"""End-to-end behaviour of POST /api/v1/extract, with the model stubbed out."""

from __future__ import annotations

from app.errors import ModelError, ModelNotConfiguredError, ModelTimeoutError
from app.schemas import (
    ExtractedReferralData,
    PatientDemographics,
    PrimaryInsurance,
)
from tests.conftest import StubExtractor

URL = "/api/v1/extract"


def _filled() -> ExtractedReferralData:
    return ExtractedReferralData(
        patient_demographics=PatientDemographics(
            name="Jane Doe", dob="01/15/1980", phone="555-0198", email=""
        ),
        primary_insurance=PrimaryInsurance(
            member_id="ABC123456789", insurance_name="Blue Cross"
        ),
    )


def test_extracts_and_returns_data_with_meta(make_client, upload):
    stub = StubExtractor(result=_filled())
    client = make_client(stub)

    response = client.post(URL, files=upload)

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["patient_demographics"]["name"] == "Jane Doe"
    assert body["data"]["patient_demographics"]["email"] == ""
    assert body["data"]["secondary_insurance"]["member_id"] == ""
    assert body["meta"]["filename"] == "referral.pdf"
    assert body["meta"]["content_type"] == "application/pdf"
    assert body["meta"]["model"] == "stub-model"
    assert body["meta"]["request_id"] == response.headers["X-Request-ID"]


def test_unversioned_alias_still_works(make_client, upload):
    """The original clients posted to /extract; that route must keep working."""
    client = make_client(StubExtractor(result=_filled()))

    response = client.post("/extract", files=upload)

    assert response.status_code == 200
    assert response.json()["data"]["patient_demographics"]["name"] == "Jane Doe"


def test_document_reaches_the_extractor_intact(make_client, upload, pdf_bytes):
    stub = StubExtractor()
    client = make_client(stub)

    client.post(URL, files=upload)

    assert len(stub.calls) == 1
    assert stub.calls[0].content == pdf_bytes


def test_missing_file_is_a_validation_error(client):
    response = client.post(URL)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_empty_file_is_rejected(client):
    response = client.post(URL, files={"file": ("empty.pdf", b"", "application/pdf")})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"


def test_oversized_file_is_rejected(make_client, pdf_bytes):
    client = make_client(max_upload_bytes=256)

    response = client.post(
        URL, files={"file": ("big.pdf", pdf_bytes + b"0" * 4096, "application/pdf")}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_non_document_upload_is_rejected(client):
    response = client.post(URL, files={"file": ("notes.txt", b"hello", "text/plain")})

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_missing_credentials_surface_as_503(make_client, upload):
    client = make_client(StubExtractor(error=ModelNotConfiguredError()))

    response = client.post(URL, files=upload)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_configured"


def test_model_timeout_surfaces_as_504(make_client, upload):
    client = make_client(StubExtractor(error=ModelTimeoutError()))

    response = client.post(URL, files=upload)

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "model_timeout"


def test_model_failure_surfaces_as_502(make_client, upload):
    client = make_client(StubExtractor(error=ModelError()))

    response = client.post(URL, files=upload)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "model_error"


def test_unexpected_error_does_not_leak_internals(make_client, upload):
    secret = "postgres://user:hunter2@db.internal/prod"
    client = make_client(StubExtractor(error=RuntimeError(secret)))

    response = client.post(URL, files=upload)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert secret not in response.text


def test_error_bodies_carry_a_request_id(client):
    response = client.post(URL, files={"file": ("x.txt", b"nope", "text/plain")})

    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
