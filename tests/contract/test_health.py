"""T010 — `/health` contract: dependency-free liveness.

The health endpoint must answer 200 even when Supabase is completely
unreachable and regardless of `ENABLE_AUTH`, proving it has zero upstream
dependencies (Constitution III, tasks.md T006/T010).
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

HEALTH_PATHS = ("/health", "/api/v1/health")


def _hard_fail(*args, **kwargs):
    raise httpx.ConnectError("supabase unreachable (test)")


class TestHealthDependencyFreedom:
    @pytest.mark.parametrize("path", HEALTH_PATHS)
    def test_ok_with_supabase_hard_failing(self, client, path):
        """Every Supabase entry point raises; /health must still be 200."""
        with (
            patch("supabase.create_async_client", side_effect=_hard_fail),
            patch("app.deps.db._create_client", side_effect=_hard_fail),
        ):
            response = client.get(path)

        assert response.status_code == 200
        assert response.json()["ok"] is True

    @pytest.mark.parametrize("path", HEALTH_PATHS)
    def test_ok_with_supabase_env_missing(self, client, settings_override, path):
        """No Supabase configuration at all still yields 200."""
        with settings_override(
            {
                "SUPABASE_URL": "",
                "SUPABASE_ANON_KEY": "",
                "SUPABASE_SERVICE_ROLE_KEY": "",
            }
        ):
            response = client.get(path)

        assert response.status_code == 200
        assert response.json()["ok"] is True

    @pytest.mark.parametrize("path", HEALTH_PATHS)
    def test_never_gated_by_auth(self, client, settings_override, path):
        """ENABLE_AUTH=true must not gate the health paths."""
        with settings_override({"ENABLE_AUTH": "true"}):
            response = client.get(path)

        assert response.status_code == 200

    @pytest.mark.parametrize("path", HEALTH_PATHS)
    def test_invalid_token_does_not_break_health(self, client, path):
        """A malformed bearer token is ignored on the health paths."""
        response = client.get(path, headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 200

    def test_response_shape(self, client):
        body = client.get("/api/v1/health").json()
        for key in ("ok", "service", "model", "provider", "project", "location"):
            assert key in body, f"missing health field: {key}"

    @pytest.mark.parametrize("path", HEALTH_PATHS)
    def test_correlation_id_present(self, client, path):
        response = client.get(path)
        assert response.headers.get("X-Correlation-Id")
