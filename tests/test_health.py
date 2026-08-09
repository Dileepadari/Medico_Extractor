"""Health, readiness, docs exposure and response headers."""

from __future__ import annotations

from app import __version__


def test_healthz_is_ok_without_credentials(make_client):
    client = make_client(google_api_key=None)
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_readyz_is_ready_when_configured(client):
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["model_credentials"] == "ok"


def test_readyz_reports_not_ready_without_credentials(make_client):
    client = make_client(google_api_key=None)
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["model_credentials"] == "missing"


def test_every_response_carries_a_request_id(client):
    response = client.get("/healthz")

    assert response.headers["X-Request-ID"]


def test_upstream_request_id_is_preserved(client):
    response = client.get("/healthz", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["X-Request-ID"] == "trace-abc-123"


def test_security_headers_are_present(client):
    headers = client.get("/healthz").headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"


def test_hsts_only_in_production(make_client):
    dev = make_client()
    prod = make_client(environment="production", cors_origins=["https://example.com"])

    assert "Strict-Transport-Security" not in dev.get("/healthz").headers
    assert "Strict-Transport-Security" in prod.get("/healthz").headers


def test_docs_are_hidden_in_production(make_client):
    prod = make_client(environment="production", cors_origins=["https://example.com"])

    assert prod.get("/docs").status_code == 404
    assert prod.get("/openapi.json").status_code == 404


def test_docs_are_available_in_development(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_root_returns_service_info_when_frontend_disabled(client):
    body = client.get("/").json()

    assert body["service"] == "medico-extractor"
    assert body["extract"] == "/api/v1/extract"


def test_unknown_route_returns_structured_error(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
