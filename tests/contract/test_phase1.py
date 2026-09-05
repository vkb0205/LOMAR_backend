"""Core application composition contracts."""

import pytest


class TestHealth:
    @pytest.mark.parametrize("path", ["/health", "/api/v1/health", "/api/v1/public/health"])
    def test_health_is_public(self, client, path):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_health_shape(self, client):
        body = client.get("/health").json()
        assert body["service"] == "LOMAR Backend API"


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
