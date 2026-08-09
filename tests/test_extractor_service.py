"""The extractor's retry, timeout and error-mapping behaviour."""

from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.errors import ModelError, ModelNotConfiguredError, ModelTimeoutError
from app.schemas import ExtractedReferralData
from app.services.documents import ValidatedDocument
from app.services.extractor import ReferralExtractor, _is_retryable

DOCUMENT = ValidatedDocument(
    content=b"%PDF-1.4 fake", content_type="application/pdf", filename="r.pdf"
)


def _settings(**overrides) -> Settings:
    base = {
        "google_api_key": "test-key",
        "gemini_max_retries": 2,
        "gemini_timeout_seconds": 5,
        "_env_file": None,
    }
    return Settings(**{**base, **overrides})


class FakeLLM:
    """Records invocations and replays a scripted sequence of outcomes."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


def _extractor(llm, **overrides) -> ReferralExtractor:
    extractor = ReferralExtractor(_settings(**overrides))
    extractor._structured_llm = llm
    return extractor


async def test_returns_the_models_structured_output():
    expected = ExtractedReferralData()
    extractor = _extractor(FakeLLM(expected))

    assert await extractor.extract(DOCUMENT) is expected


async def test_accepts_a_dict_from_structured_output():
    payload = {"patient_demographics": {"name": "Jane Doe"}}
    extractor = _extractor(FakeLLM(payload))

    result = await extractor.extract(DOCUMENT)

    assert result.patient_demographics.name == "Jane Doe"


async def test_retries_a_transient_failure_then_succeeds():
    llm = FakeLLM(RuntimeError("503 Service Unavailable"), ExtractedReferralData())
    extractor = _extractor(llm)

    await extractor.extract(DOCUMENT)

    assert llm.calls == 2


async def test_gives_up_after_the_configured_retries():
    llm = FakeLLM(RuntimeError("429 resource exhausted"))
    extractor = _extractor(llm, gemini_max_retries=1)

    with pytest.raises(ModelError):
        await extractor.extract(DOCUMENT)

    assert llm.calls == 2  # the first attempt plus one retry


async def test_does_not_retry_a_permanent_failure():
    llm = FakeLLM(ValueError("invalid document schema"))
    extractor = _extractor(llm)

    with pytest.raises(ModelError):
        await extractor.extract(DOCUMENT)

    assert llm.calls == 1


async def test_timeout_maps_to_model_timeout_error():
    async def _hang():
        await asyncio.sleep(5)

    extractor = _extractor(FakeLLM(_hang), gemini_timeout_seconds=0.05)

    with pytest.raises(ModelTimeoutError):
        await extractor.extract(DOCUMENT)


async def test_none_from_the_model_is_an_error():
    extractor = _extractor(FakeLLM(None))

    with pytest.raises(ModelError):
        await extractor.extract(DOCUMENT)


async def test_missing_credentials_raise_before_any_call():
    extractor = ReferralExtractor(_settings(google_api_key=None))

    with pytest.raises(ModelNotConfiguredError):
        await extractor.extract(DOCUMENT)


async def test_provider_message_is_not_echoed_to_the_client():
    leak = "API key AIzaSyINVALID rejected"
    extractor = _extractor(FakeLLM(RuntimeError(leak)))

    with pytest.raises(ModelError) as excinfo:
        await extractor.extract(DOCUMENT)

    assert "AIzaSy" not in str(excinfo.value)
    assert "credentials" in str(excinfo.value)


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        (RuntimeError("503 unavailable"), True),
        (RuntimeError("429 Too Many Requests"), True),
        (RuntimeError("connection reset by peer"), True),
        (RuntimeError("model is overloaded"), True),
        (ValueError("malformed request"), False),
        (TimeoutError(), False),
    ],
)
def test_retry_classification(exc, retryable):
    assert _is_retryable(exc) is retryable


def test_pdfs_are_sent_as_file_blocks():
    messages = ReferralExtractor._build_messages(DOCUMENT)
    block = messages[1].content[1]

    assert block["type"] == "file"
    assert block["mime_type"] == "application/pdf"
    assert block["base64"]


def test_images_are_sent_as_image_blocks():
    image = ValidatedDocument(
        content=b"\x89PNG\r\n\x1a\n", content_type="image/png", filename="s.png"
    )

    block = ReferralExtractor._build_messages(image)[1].content[1]

    assert block["type"] == "image"
    assert block["mime_type"] == "image/png"
