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
        assert data["service"] == "LOMAR Vertex AI Nano Banana VTON API"
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
        resp = client.post("/test-try-on", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        assert "fields" in body["error"]

    def test_unauthenticated_uses_envelope(self, client, settings_override):
        """With auth enabled, a protected path without a token returns 401."""
        with settings_override({"ENABLE_AUTH": "true"}):
            resp = client.post("/consult", json={"message": "hi"})
            assert resp.status_code == 401
            body = resp.json()
            assert body["error"]["code"] == "unauthenticated"


# ---------------------------------------------------------------------------
# Legacy VTON endpoints: contract shape only (AI provider mocked)
# ---------------------------------------------------------------------------


class TestVtonContract:
    def test_test_try_on_requires_body(self, client):
        """Missing required fields → 422 validation_error."""
        resp = client.post("/test-try-on", json={})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    def test_test_try_on_invalid_url(self, client):
        """Non-http(s) URLs are rejected."""
        resp = client.post(
            "/test-try-on",
            json={
                "body_image": "not-a-url",
                "garment_image": "also-not-a-url",
                "category": "ao-dai",
            },
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    def test_proxy_image_rejects_blocked_url(self, client):
        """SSRF guard rejects private/reserved addresses before any fetch."""
        resp = client.get("/proxy-image", params={"url": "http://169.254.169.254/meta"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    def test_consult_requires_message(self, client):
        resp = client.post("/consult", json={})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    def test_upload_missing_files(self, client):
        resp = client.post(
            "/test-try-on-upload",
            data={"category": "ao-dai", "prompt": ""},
        )
        assert resp.status_code == 422
