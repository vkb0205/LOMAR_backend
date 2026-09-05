"""Core application composition contracts."""

import pytest


class TestHealth:
    @pytest.mark.parametrize("path", ["/health", "/api/v1/health", "/api/v1/public/health"])
    def test_health_is_public(self, client, path):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_health_shape(self, client):
        """Response matches the shape documented in LOMAR/README.md."""
        resp = client.get("/health")
        data = resp.json()
        assert data["ok"] is True
        assert data["service"] == "LOMAR Backend API"
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
    def test_success_and_error_responses_have_correlation_id(self, client):
        assert client.get("/health").headers.get("X-Correlation-Id")
        missing = client.get("/does-not-exist")
        assert missing.status_code == 404
        assert missing.headers.get("X-Correlation-Id")


class TestRetiredLegacyRoutes:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/proxy-image"),
            ("POST", "/test-try-on"),
            ("POST", "/test-try-on-upload"),
            ("POST", "/consult"),
        ],
    )
    def test_legacy_vton_routes_are_not_mounted(self, client, method, path):
        assert client.request(method, path).status_code == 404


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
