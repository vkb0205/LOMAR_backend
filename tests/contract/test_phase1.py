"""Contract tests for Phase 1: health, middleware, and error envelope.

Per Constitution VI these assert status codes, request validation, and
response shape — never live providers.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_unauthenticated_ok(self, client):
        """GET /health returns 200 without any auth header."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_shape(self, client):
        """Response matches the shape documented in LOMAR/README.md."""
        resp = client.get("/health")
        data = resp.json()
        assert data["ok"] is True
        assert data["service"] == "LOMAR Business Intelligence API"
        assert "model" in data
        assert "provider" in data
        assert "project" in data
        assert "location" in data
        assert "vertex_configured" in data

    def test_health_v1_alias(self, client):
        """The /api/v1/health alias also exists."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_health_never_gated_by_auth(self, client, settings_override):
        """Constitution III: /health answers without upstreams, even with auth on."""
        with settings_override({"ENABLE_AUTH": "true"}):
            resp = client.get("/health")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Middleware: X-Correlation-Id
# ---------------------------------------------------------------------------


class TestCorrelationId:
    def test_response_has_correlation_id(self, client):
        resp = client.get("/health")
        assert "x-correlation-id" in resp.headers
        assert len(resp.headers["x-correlation-id"]) > 0

    def test_passthrough_of_client_supplied_id(self, client):
        resp = client.get(
            "/health", headers={"X-Correlation-Id": "client-provided-123"}
        )
        assert resp.headers["x-correlation-id"] == "client-provided-123"

    def test_error_responses_also_carry_correlation_id(self, client):
        """Errors must include the correlation id so tracing works on failures."""
        resp = client.get("/does-not-exist")
        assert resp.status_code == 404
        assert "x-correlation-id" in resp.headers


# ---------------------------------------------------------------------------
# Error envelope (research.md R5)
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    def test_not_found_uses_envelope(self, client):
        resp = client.get("/definitely/missing")
        body = resp.json()
        assert body["error"]["code"] == "not_found"
        assert "message" in body["error"]

    def test_validation_error_uses_envelope(self, client):
        """FastAPI's own validation errors are remapped to the envelope."""
        from tests.conftest import TEST_ADMIN_ID, factory_token

        resp = client.post(
            "/api/v1/business-intelligence/agents/run",
            headers={"Authorization": f"Bearer {factory_token(TEST_ADMIN_ID, role='admin')}"},
            json={},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        assert "fields" in body["error"]

    def test_unauthenticated_uses_envelope(self, client):
        """Protected BI paths require a valid caller token."""
        resp = client.post("/api/v1/business-intelligence/chat", json={"message": "hi"})
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "unauthenticated"
