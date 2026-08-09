"""API key enforcement and rate limiting."""

from __future__ import annotations

import pytest

from app.errors import RateLimitedError
from app.security import SlidingWindowRateLimiter

URL = "/api/v1/extract"


def test_no_key_configured_means_open_access(client, upload):
    assert client.post(URL, files=upload).status_code == 200


def test_request_without_key_is_rejected_when_one_is_configured(make_client, upload):
    client = make_client(api_key="s3cret")

    response = client.post(URL, files=upload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_wrong_key_is_rejected(make_client, upload):
    client = make_client(api_key="s3cret")

    response = client.post(URL, files=upload, headers={"X-API-Key": "guess"})

    assert response.status_code == 401


def test_correct_key_is_accepted(make_client, upload):
    client = make_client(api_key="s3cret")

    response = client.post(URL, files=upload, headers={"X-API-Key": "s3cret"})

    assert response.status_code == 200


def test_bearer_token_is_accepted_too(make_client, upload):
    client = make_client(api_key="s3cret")

    response = client.post(
        URL, files=upload, headers={"Authorization": "Bearer s3cret"}
    )

    assert response.status_code == 200


def test_health_endpoints_never_require_a_key(make_client):
    client = make_client(api_key="s3cret")

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_rate_limit_blocks_the_request_over_budget(make_client, upload, pdf_bytes):
    client = make_client(rate_limit_requests=2, rate_limit_window_seconds=60)
    files = lambda: {"file": ("r.pdf", pdf_bytes, "application/pdf")}  # noqa: E731

    assert client.post(URL, files=files()).status_code == 200
    assert client.post(URL, files=files()).status_code == 200

    third = client.post(URL, files=files())
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"
    assert int(third.headers["Retry-After"]) > 0


def test_rate_limit_is_per_client_ip(make_client, upload, pdf_bytes):
    client = make_client(rate_limit_requests=1, rate_limit_window_seconds=60)
    files = lambda: {"file": ("r.pdf", pdf_bytes, "application/pdf")}  # noqa: E731

    assert client.post(URL, files=files(), headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    assert client.post(URL, files=files(), headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429
    assert client.post(URL, files=files(), headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200


def test_limiter_window_slides():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10)

    limiter.check("ip", now=100.0)
    limiter.check("ip", now=100.5)
    with pytest.raises(RateLimitedError):
        limiter.check("ip", now=101.0)

    # Once the first hits age out of the window, the budget is free again.
    limiter.check("ip", now=111.0)


def test_limiter_is_a_noop_when_disabled():
    limiter = SlidingWindowRateLimiter(max_requests=0, window_seconds=60)

    for _ in range(100):
        limiter.check("ip")

    assert not limiter.enabled
