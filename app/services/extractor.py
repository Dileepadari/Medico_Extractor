"""Gemini-backed extraction of structured referral data.

The document is sent to the model as-is (PDF or image) rather than being
OCR'd first: Gemini reads scanned faxes natively, which removes an entire class
of preprocessing bugs and a pile of system dependencies. Pydantic-typed
structured output means the model returns the exact schema the API promises,
so no free-text parsing happens anywhere downstream.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings
from app.errors import ModelError, ModelNotConfiguredError, ModelTimeoutError
from app.schemas import ExtractedReferralData
from app.services.documents import ValidatedDocument

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are an expert medical data extraction algorithm. Extract the requested "
    "patient, insurance, and referral information from the provided document.\n"
    "Rules:\n"
    "- Transcribe values exactly as they appear in the document.\n"
    "- Never infer, guess, or complete a partially visible value.\n"
    "- If a field is absent or unreadable, return an empty string for it.\n"
    "- If the document contains several patients, use the referred patient.\n"
    "- The referral source is the *referring* provider, not the receiving clinic."
)

USER_INSTRUCTION = "Extract the required data from this document."

# Substrings that mark a failure as worth retrying (rate limits, transient 5xx,
# connection resets). Matched against the exception text because the underlying
# SDK raises a mix of its own error types and plain transport errors.
_RETRYABLE_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "resource_exhausted",
    "resource exhausted",
    "unavailable",
    "internal error",
    "deadline exceeded",
    "connection reset",
    "connection aborted",
    "temporarily",
    "overloaded",
)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return False  # the caller's overall deadline governs, not a retry
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _RETRYABLE_MARKERS)


class ReferralExtractor:
    """Wraps the chat model with the retry, timeout and error mapping we want."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._structured_llm: Any | None = None

    @property
    def model_name(self) -> str:
        return self._settings.gemini_model

    @property
    def is_configured(self) -> bool:
        return self._settings.model_configured

    def _get_llm(self) -> Any:
        """Build the model client on first use.

        Deferred so the app imports (and `/healthz` answers) without credentials,
        and so a missing key is a clean 503 rather than an import-time crash.
        """
        if self._structured_llm is not None:
            return self._structured_llm

        if not self.is_configured:
            raise ModelNotConfiguredError()

        # Imported lazily: the google-genai client is heavy and only needed here.
        from langchain_google_genai import ChatGoogleGenerativeAI

        assert self._settings.google_api_key is not None
        llm = ChatGoogleGenerativeAI(
            model=self._settings.gemini_model,
            temperature=self._settings.gemini_temperature,
            google_api_key=self._settings.google_api_key.get_secret_value(),
            timeout=self._settings.gemini_timeout_seconds,
            max_retries=0,  # retries are handled here, with our own policy
        )
        self._structured_llm = llm.with_structured_output(ExtractedReferralData)
        return self._structured_llm

    def warm_up(self) -> None:
        """Build the client at startup so the first real request isn't the slowest."""
        if self.is_configured:
            self._get_llm()

    @staticmethod
    def _build_messages(document: ValidatedDocument) -> list[Any]:
        encoded = base64.b64encode(document.content).decode("utf-8")
        block_type = "file" if document.content_type == "application/pdf" else "image"
        return [
            SystemMessage(content=SYSTEM_INSTRUCTION),
            HumanMessage(
                content=[
                    {"type": "text", "text": USER_INSTRUCTION},
                    {
                        "type": block_type,
                        "base64": encoded,
                        "mime_type": document.content_type,
                    },
                ]
            ),
        ]

    async def extract(self, document: ValidatedDocument) -> ExtractedReferralData:
        """Run extraction, translating every failure into an `AppError`."""
        llm = self._get_llm()
        messages = self._build_messages(document)
        settings = self._settings

        started = time.perf_counter()
        attempt_number = 0

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max(1, settings.gemini_max_retries + 1)),
                wait=wait_exponential(multiplier=1, min=1, max=8),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    attempt_number = attempt.retry_state.attempt_number
                    if attempt_number > 1:
                        logger.warning(
                            "retrying extraction",
                            extra={"attempt": attempt_number},
                        )
                    result = await asyncio.wait_for(
                        llm.ainvoke(messages),
                        timeout=settings.gemini_timeout_seconds,
                    )
        except TimeoutError as exc:
            logger.warning(
                "extraction timed out",
                extra={
                    "timeout_seconds": settings.gemini_timeout_seconds,
                    "attempts": attempt_number,
                },
            )
            raise ModelTimeoutError(
                f"Extraction exceeded the {settings.gemini_timeout_seconds:.0f}s "
                "limit. Try a smaller or lower-resolution document."
            ) from exc
        except RetryError as exc:  # pragma: no cover - reraise=True makes this rare
            raise ModelError() from exc
        except Exception as exc:
            # Log the type and message but never the document or the prompt.
            logger.error(
                "extraction failed: %s: %s",
                type(exc).__name__,
                exc,
                extra={"attempts": attempt_number},
            )
            raise ModelError(self._client_message(exc)) from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "extraction succeeded",
            extra={
                "duration_ms": duration_ms,
                "attempts": attempt_number,
                "model": settings.gemini_model,
                "size_bytes": document.size_bytes,
                "content_type": document.content_type,
            },
        )
        return self._coerce(result)

    @staticmethod
    def _client_message(exc: Exception) -> str:
        """Turn a provider error into something safe and actionable for a caller."""
        text = str(exc).lower()
        if "api key" in text or "unauthenticated" in text or "permission" in text:
            return "The extraction service rejected our credentials."
        if "429" in text or "quota" in text or "exhausted" in text:
            return "The extraction service is rate limited right now. Retry shortly."
        if "safety" in text or "blocked" in text:
            return "The model declined to process this document."
        return "The extraction model failed to process this document."

    @staticmethod
    def _coerce(result: Any) -> ExtractedReferralData:
        """Normalise whatever structured output handed back into our model."""
        if isinstance(result, ExtractedReferralData):
            return result
        if isinstance(result, dict):
            return ExtractedReferralData.model_validate(result)
        if result is None:
            raise ModelError("The model returned no data for this document.")
        raise ModelError("The model returned data in an unexpected shape.")
