"""Unit tests for ``app.deps.auth``.

Covers:
- ``current_user`` with valid / missing / expired / bad-audience tokens.
- ``require_user`` rejecting empty user_id.
- ``require_admin`` requiring db lookup of ``profiles.role == 'admin'``.
"""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings
from app.deps.auth import AuthenticatedUser, current_user, require_admin, require_user
from app.errors import ForbiddenError, UnauthenticatedError, register_exception_handlers

SECRET = "test-supabase-jwt-secret"
AUDIENCE = "authenticated"


def _token(user_id="111", role="customer", *, expired=False, bad_aud=False) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "aud": "wrong" if bad_aud else AUDIENCE,
        "exp": now - 60 if expired else now + 3600,
        "role": role,
        "email": "test@example.com",
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _encode(token: str) -> str:
    return f"Bearer {token}"


# ---------------------------------------------------------------------------
# FastAPI test app
# ---------------------------------------------------------------------------

app = FastAPI()
register_exception_handlers(app)  # so ApiError subclasses return proper status codes


@app.get("/public")
async def public_route(user: AuthenticatedUser = Depends(current_user)):
    return {"user_id": user.user_id, "role": user.role}


@app.get("/private")
async def private_route(user: AuthenticatedUser = Depends(require_user)):
    return {"user_id": user.user_id}


@app.get("/admin")
async def admin_route(user: AuthenticatedUser = Depends(require_admin)):
    return {"user_id": user.user_id}


client = TestClient(app)


def _req(headers: dict | None = None):
    h = {"authorization": "", **(headers or {})}
    return client.get("/", headers=h)


# ---------------------------------------------------------------------------
# Tests: current_user
# ---------------------------------------------------------------------------


class TestCurrentUser:
    def test_missing_header(self):
        resp = client.get("/public")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == ""

    def test_invalid_scheme(self):
        resp = client.get("/public", headers={"authorization": "Token abc"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == ""

    def test_valid_token(self):
        token = _token("user-abc", role="vendor")
        resp = client.get("/public", headers={"authorization": _encode(token)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-abc"
        assert data["role"] == "vendor"

    def test_expired_token(self):
        token = _token("user-abc", expired=True)
        resp = client.get("/public", headers={"authorization": _encode(token)})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == ""  # degraded to anonymous

    def test_bad_audience(self):
        token = _token("user-abc", bad_aud=True)
        resp = client.get("/public", headers={"authorization": _encode(token)})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == ""


# ---------------------------------------------------------------------------
# Tests: require_user
# ---------------------------------------------------------------------------


class TestRequireUser:
    def test_anonymous_rejected(self):
        resp = client.get("/private")
        # FastAPI raises HTTPException(401) which becomes a JSON body
        assert resp.status_code == 401

    def test_authenticated_accepted(self):
        token = _token("user-abc")
        resp = client.get("/private", headers={"authorization": _encode(token)})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "user-abc"


# ---------------------------------------------------------------------------
# Tests: require_admin  (requires a fake Supabase client on request.state)
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    def _make_request(self, token: str) -> StarletteRequest:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/admin",
            "headers": [(b"authorization", _encode(token).encode())],
            "query_string": b"",
        }
        return StarletteRequest(scope)

    def _mock_supabase_admin_lookup(self, role: str):
        """Mock Supabase client where profiles lookup returns *role*."""
        mock = MagicMock()
        result = MagicMock()
        result.data = {"role": role}
        mock.table.return_value.select.return_value.eq.return_value.single.return_value.execute = AsyncMock(return_value=result)
        return mock

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self):
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": SECRET}):
            get_settings.cache_clear()
            token = _token("user-abc", role="customer")
            req = self._make_request(token)
            req.state.supabase = self._mock_supabase_admin_lookup("customer")
            user = AuthenticatedUser(user_id="user-abc", role=None)
            with pytest.raises(ForbiddenError):
                await require_admin(user, req)
            get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_admin_accepted(self):
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": SECRET}):
            get_settings.cache_clear()
            token = _token("admin-abc", role="admin")
            req = self._make_request(token)
            req.state.supabase = self._mock_supabase_admin_lookup("admin")
            user = AuthenticatedUser(user_id="admin-abc", role="admin")
            result = await require_admin(user, req)
            assert result.user_id == "admin-abc"
            assert result.role == "admin"
            get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_anonymous_raises_401(self):
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": SECRET}):
            get_settings.cache_clear()
            req = self._make_request("")
            req.state.supabase = None
            user = AuthenticatedUser(user_id="")
            with pytest.raises(UnauthenticatedError):
                await require_admin(user, req)
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Tests: ES256 / JWKS path (Supabase asymmetric signing)
# ---------------------------------------------------------------------------


class TestAsymmetricJwt:
    def test_es256_token_accepted_via_jwks(self, monkeypatch):
        """Tokens signed ES256 must verify against the JWKS public key."""
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        from app.deps import auth as auth_mod
        from app.deps.auth import _decode_token

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "es256-user",
                "aud": AUDIENCE,
                "exp": now + 3600,
                "role": "admin",
            },
            private_key,
            algorithm="ES256",
            headers={"kid": "test-es256-kid"},
        )

        class _Key:
            def __init__(self, key):
                self.key = key

        class _Client:
            def get_signing_key_from_jwt(self, _token):
                return _Key(public_key)

        monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
        monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
        monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", AUDIENCE)
        get_settings.cache_clear()
        auth_mod._jwks_client = None
        auth_mod._jwks_client_url = None

        monkeypatch.setattr(auth_mod, "_get_jwks_client", lambda _settings: _Client())

        payload = _decode_token(token)
        assert payload.sub == "es256-user"
        assert payload.role == "admin"
        get_settings.cache_clear()

    def test_unknown_alg_rejected(self, monkeypatch):
        from app.deps.auth import _decode_token
        from app.errors import UnauthenticatedError

        # none-alg style header is rejected by algorithm allowlist before verify
        # Build a minimal three-segment token with alg=none via jwt lib if possible.
        # PyJWT refuses to encode alg=none by default; craft header manually.
        import base64, json

        def b64(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        body = b64(json.dumps({"sub": "x", "aud": AUDIENCE, "exp": int(time.time()) + 60}).encode())
        token = f"{header}.{body}."

        monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
        get_settings.cache_clear()
        with pytest.raises(UnauthenticatedError) as ei:
            _decode_token(token)
        assert "alg value is not allowed" in str(ei.value)
        get_settings.cache_clear()
