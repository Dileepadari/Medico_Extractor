"""Settings parsing and startup warnings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_comma_separated_origins_are_split():
    settings = _settings(cors_origins="https://a.example, https://b.example")

    assert settings.cors_origins == ["https://a.example", "https://b.example"]


def test_a_real_list_is_left_alone():
    assert _settings(cors_origins=["https://a.example"]).cors_origins == [
        "https://a.example"
    ]


def test_log_level_is_normalised():
    assert _settings(log_level="debug").log_level == "DEBUG"


def test_invalid_log_level_is_rejected():
    with pytest.raises(ValidationError):
        _settings(log_level="chatty")


def test_docs_default_off_in_production_and_on_elsewhere():
    assert _settings(environment="production").docs_enabled is False
    assert _settings(environment="development").docs_enabled is True


def test_docs_can_be_forced_on_in_production():
    assert _settings(environment="production", enable_docs=True).docs_enabled is True


def test_api_key_is_not_printed_in_a_repr():
    settings = _settings(api_key="super-secret", google_api_key="also-secret")

    assert "super-secret" not in repr(settings)
    assert "also-secret" not in repr(settings)


def test_missing_credentials_produce_a_startup_warning():
    warnings = _settings(google_api_key=None).startup_warnings()

    assert any("GOOGLE_API_KEY" in warning for warning in warnings)


def test_production_warns_about_wildcard_cors_and_open_access():
    warnings = _settings(
        environment="production", google_api_key="k", cors_origins=["*"]
    ).startup_warnings()

    assert any("CORS_ORIGINS" in warning for warning in warnings)
    assert any("API_KEY" in warning for warning in warnings)


def test_a_locked_down_production_config_is_quiet():
    settings = _settings(
        environment="production",
        google_api_key="k",
        api_key="a",
        cors_origins=["https://app.example"],
    )

    assert settings.startup_warnings() == []
