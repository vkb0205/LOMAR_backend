"""T011 — middleware contract: CORS allowlist, correlation ID, DB timeout.

`/api/v1` domain routers do not exist yet (Phase 2+), so the
timeout-to-503 mapping is exercised directly against
:func:`app.deps.db.run_db`, which is the single chokepoint every future
repository call must go through (research.md R5, SC-005).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.deps.db import run_db
from app.errors import DatabaseUnavailableError


class TestCorsAllowlist:
    def test_allowed_origin_echoed(self, client):
        response = client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_disallowed_origin_not_echoed(self, client):
        response = client.get(
            "/health",
            headers={"Origin": "http://evil.example.com"},
        )
        assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"

    def test_preflight_allowed_origin(self, client):
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code in (200, 204)
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_wildcard_never_configured(self, app):
        """Constitution IV: CORS allowlist must never be a literal '*'."""
        from starlette.middleware.cors import CORSMiddleware

        cors_layers = [
            m for m in app.user_middleware if m.cls is CORSMiddleware
        ]
        assert cors_layers, "CORSMiddleware must be registered"
        options = cors_layers[0].kwargs
        assert "*" not in options.get("allow_origins", [])


class TestCorrelationId:
    def test_present_on_success(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Correlation-Id")

    def test_present_on_unknown_v1_path_is_404(self, client):
        """Dependencies protect declared routes; middleware does not turn an
        unknown route into an authentication oracle."""
        response = client.get("/api/v1/does-not-exist")
        assert response.headers.get("X-Correlation-Id")
        assert response.status_code == 404

    def test_present_on_404_for_unknown_legacy_path(self, client):
        response = client.get("/does-not-exist")
        assert response.headers.get("X-Correlation-Id")
        assert response.status_code == 404

    def test_client_supplied_id_is_echoed(self, client):
        response = client.get("/health", headers={"X-Correlation-Id": "abc-123"})
        assert response.headers.get("X-Correlation-Id") == "abc-123"

    def test_client_supplied_id_echoed_on_preserved_bi_route(self, client, settings_override):
        with settings_override({"ENABLE_AUTH": "true"}):
            response = client.get("/api/v1/business-intelligence/overview", headers={"X-Correlation-Id": "xyz-789"})
        assert response.headers.get("X-Correlation-Id") == "xyz-789"
        assert response.status_code == 401


class TestDbTimeoutMapsTo503:
    @pytest.mark.asyncio
    async def test_asyncio_timeout_raises_database_unavailable(self):
        async def _hangs():
            raise asyncio.TimeoutError()

        with pytest.raises(DatabaseUnavailableError) as exc_info:
            await run_db(_hangs)
        assert exc_info.value.status_code == 503
        assert exc_info.value.to_body()["error"]["code"] == "database_unavailable"

    @pytest.mark.asyncio
    async def test_httpx_connect_error_raises_database_unavailable(self):
        async def _unreachable():
            raise httpx.ConnectError("connection refused")

        with pytest.raises(DatabaseUnavailableError):
            await run_db(_unreachable)

    @pytest.mark.asyncio
    async def test_httpx_read_timeout_raises_database_unavailable(self):
        async def _slow():
            raise httpx.ReadTimeout("timed out")

        with pytest.raises(DatabaseUnavailableError):
            await run_db(_slow)

    @pytest.mark.asyncio
    async def test_database_unavailable_never_leaks_upstream_text(self):
        secret_detail = "internal postgres connection string leaked"

        async def _fails():
            raise httpx.ConnectError(secret_detail)

        with pytest.raises(DatabaseUnavailableError) as exc_info:
            await run_db(_fails)

        body = exc_info.value.to_body()
        assert secret_detail not in str(body)

    @pytest.mark.asyncio
    async def test_non_network_error_is_not_masked(self):
        """A genuine application bug must not be silently turned into 503."""

        async def _bug():
            raise ValueError("not a network error")

        with pytest.raises(ValueError):
            await run_db(_bug)

    @pytest.mark.asyncio
    async def test_success_passes_through(self):
        async def _ok():
            return {"data": [1, 2, 3]}

        result = await run_db(_ok)
        assert result == {"data": [1, 2, 3]}
