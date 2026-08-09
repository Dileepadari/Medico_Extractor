"""Application settings, loaded from environment variables (and `.env` locally)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every knob the service exposes. See `.env.example` for documentation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Environment -----------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- HTTP ------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    root_path: str = ""
    # Comma-separated list. "*" is rejected in production (see validator below).
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    # Serve the bundled single-page frontend from "/". Disable for API-only deploys.
    serve_frontend: bool = True
    # Expose /docs, /redoc and /openapi.json. Off by default in production.
    enable_docs: bool | None = None

    # --- Upload limits ---------------------------------------------------
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MiB
    allowed_content_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/webp",
        ]
    )

    # --- Model -----------------------------------------------------------
    google_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.0
    gemini_timeout_seconds: float = 90.0
    gemini_max_retries: int = 2

    # --- Access control --------------------------------------------------
    # When set, /extract requires a matching `X-API-Key` header.
    api_key: SecretStr | None = None
    # Per-client-IP request budget for /extract. 0 disables the limiter.
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60

    @field_validator("cors_origins", "allowed_content_types", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept both `A,B` strings (env vars) and real lists (tests, defaults)."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
            raise ValueError(f"invalid log_level: {value}")
        return level

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def docs_enabled(self) -> bool:
        if self.enable_docs is not None:
            return self.enable_docs
        return not self.is_production

    @property
    def model_configured(self) -> bool:
        return self.google_api_key is not None and bool(
            self.google_api_key.get_secret_value()
        )

    def startup_warnings(self) -> list[str]:
        """Misconfigurations worth shouting about at boot, without refusing to start.

        Anything that would make the service unusable (a missing API key) is
        reported by /readyz instead, so a container still starts and can be
        fixed by adding the variable rather than crash-looping.
        """
        warnings: list[str] = []
        if not self.model_configured:
            warnings.append(
                "GOOGLE_API_KEY is not set - /extract will return 503 until it is."
            )
        if self.is_production:
            if "*" in self.cors_origins:
                warnings.append(
                    "CORS_ORIGINS is '*' in production - set an explicit origin list."
                )
            if self.api_key is None:
                warnings.append(
                    "API_KEY is not set - /extract is open to anyone who can reach it."
                )
            if self.debug:
                warnings.append("DEBUG is enabled in production.")
        return warnings


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Call `get_settings.cache_clear()` in tests."""
    return Settings()
