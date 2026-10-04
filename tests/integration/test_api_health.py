"""API smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sot.api.app import create_app
from sot.config import ENGINE_VERSION


def client() -> TestClient:
    return TestClient(create_app())


def test_health_reports_engine_and_database():
    response = client().get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["engine_version"] == ENGINE_VERSION
    assert body["database"]["ok"] is True
    assert body["database"]["tables"] >= 20


def test_health_defaults_to_deterministic_mode():
    """Assist features reach the network, so they must be off unless switched on."""
    assert client().get("/api/health").json()["assist_enabled"] is False


def test_packs_endpoint_lists_discovered_packs():
    response = client().get("/api/packs")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["packs"], list)
    assert body["default"]


def test_unknown_route_is_a_clean_404():
    assert client().get("/api/nope").status_code == 404


def test_openapi_schema_builds():
    """A malformed route signature would only show up here, not at import time."""
    assert client().get("/api/openapi.json").status_code == 200
