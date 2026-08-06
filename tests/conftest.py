"""Shared test fixtures and helpers.

All tests run against the FastAPI ASGI app with outbound calls faked:
- Supabase is replaced by :class:`tests.fakes.FakeSupabase`, a deterministic
  in-memory store, injected via ``app.state.supabase_factory`` so both the
  caller-JWT path and the service-role path stay offline (Constitution VI).
- Google GenAI SDK calls are patched per-test.
- Environment variables are overridden per-test via ``settings_override``.

Token factory helpers use the test secret to produce valid Supabase-style JWTs
with configurable ``sub`` and ``role`` claims.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Ensure LOMAR_backend/ is importable as a package root  (project layout)
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import Settings, get_settings
from app.main import create_app
from tests.fakes import FakeSupabase

# ---------------------------------------------------------------------------
# Default test environment
# ---------------------------------------------------------------------------

TEST_SECRET = "test-supabase-jwt-secret"
TEST_AUDIENCE = "authenticated"
TEST_USER_ID = "11111111-1111-1111-1111-111111111111"
TEST_USER_B_ID = "33333333-3333-3333-3333-333333333333"
TEST_ADMIN_ID = "22222222-2222-2222-2222-222222222222"


def _default_test_env() -> dict[str, str]:
    return {
        "SUPABASE_URL": "https://test-project.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon",
        "SUPABASE_SERVICE_ROLE_KEY": "test-role",
        "SUPABASE_JWT_SECRET": TEST_SECRET,
        "SUPABASE_JWT_AUDIENCE": TEST_AUDIENCE,
        "SUPABASE_TIMEOUT_SECONDS": "8",
        "GOOGLE_CLOUD_PROJECT": "test-project",
        "GOOGLE_CLOUD_LOCATION": "global",
        "GOOGLE_TEXT_MODEL": "gemini-2.5-flash",
        "ALLOWED_ORIGINS": "http://localhost:3000",
        "API_HOST": "0.0.0.0",
        "API_PORT": "8080",
        "ENABLE_AUTH": "false",
    }


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Force test env vars and clear the lru_cache between tests."""
    for key, value in _default_test_env().items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_session_store() -> Generator[None, None, None]:
    """Reset the process-wide consultant session memory between tests.

    The store is a module-level singleton (like ``get_settings``), so without
    this a session minted by one test would remain visible to the next.
    """
    from app.services.session_store import get_session_store

    get_session_store().clear_all()
    yield
    get_session_store().clear_all()


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    application = create_app()
    application.state.supabase_factory = lambda _token: FakeSupabase(
        rows={
            "profiles": [
                {"id": TEST_USER_ID, "role": "customer"},
                {"id": TEST_USER_B_ID, "role": "customer"},
                {"id": TEST_ADMIN_ID, "role": "admin"},
            ]
        }
    )
    return application


@pytest.fixture()
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Synchronous TestClient; ``httpx`` is the underlying transport."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def async_client(app: FastAPI):
    """Optional async test client for async test functions."""
    from httpx import AsyncClient, ASGITransport

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture()
async def mock_supabase():
    """Yield a pair (anon_client, admin_client) of patched Supabase mocks.

    Each call on the client returns a chain of ``AsyncMock`` objects so that
    ``.table().select().eq().execute()`` style chains work without a real DB.
    """
    mock_anon = MagicMock()
    mock_admin = MagicMock()

    def _make_chain() -> AsyncMock:
        return AsyncMock()

    mock_anon.table = MagicMock(return_value=_make_chain())
    mock_admin.table = MagicMock(return_value=_make_chain())
    return mock_anon, mock_admin


@pytest.fixture()
def settings_override() -> Generator[dict[str, str], None, None]:
    """Context manager-like fixture: override settings then clear cache.

    Usage::

        def test_something(settings_override):
            with settings_override({"ENABLE_AUTH": "true"}):
                ... # get_settings() returns updated values
    """
    overrides: dict[str, str] = {}

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            get_settings.cache_clear()

        def __call__(self, values: dict[str, str] | None = None, **kwargs: str):
            merged = {**(values or {}), **kwargs}
            for key, value in merged.items():
                os.environ[key] = str(value)
            overrides.update(merged)
            get_settings.cache_clear()
            return _Ctx()

    yield _Ctx()
    # cleanup
    for key in overrides.keys():
        os.environ.pop(key, None)
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# JWT token factories
# ---------------------------------------------------------------------------


def factory_token(
    user_id: str = TEST_USER_ID,
    role: str = "customer",
    *,
    expire_seconds: int = 3600,
    secret: str = TEST_SECRET,
    audience: str = TEST_AUDIENCE,
) -> str:
    """Return a signed Supabase-style JWT token string."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "aud": audience,
        "exp": now + expire_seconds,
        "role": role,
        "email": "test@example.com",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture()
def user_token() -> str:
    return factory_token(TEST_USER_ID, role="customer")


@pytest.fixture()
def admin_token() -> str:
    return factory_token(TEST_ADMIN_ID, role="admin")


@pytest.fixture()
def expired_token() -> str:
    """Token that is already expired (exp in the past)."""
    now = int(time.time())
    payload = {
        "sub": TEST_USER_ID,
        "aud": TEST_AUDIENCE,
        "exp": now - 60,
        "role": "customer",
    }
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")
