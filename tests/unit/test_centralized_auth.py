"""Stage 1 — centralized Supabase JWT authentication dependency tests.

The centralized optional and required authentication dependencies are tested
end-to-end against a real FastAPI app, covering every 401
trigger called out in the stage requirements:

    * valid JWT            -> authenticated user with correct sub/email/role
    * missing JWT          -> 401
    * malformed JWT        -> 401
    * expired JWT          -> 401
    * invalid signature    -> 401
    * wrong audience       -> 401
    * unconfigured secret  -> 401
    * authenticated-user extraction returns a consistent representation
"""

from __future__ import annotations

import os
import sys
import time
from unittest.mock import patch

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.auth.dependencies import get_current_user, get_optional_user
from app.auth.models import CurrentUser
from app.config import get_settings
from app.errors import register_exception_handlers
from tests.fakes import FakeSupabase

SECRET = "test-supabase-jwt-secret"
AUDIENCE = "authenticated"


def _token(
    sub: str = "user-abc",
    *,
    email: str = "user@example.com",
    role: str = "user",
    expired: bool = False,
    bad_aud: bool = False,
    secret: str = SECRET,
    audience: str = AUDIENCE,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "aud": "wrong" if bad_aud else audience,
        "exp": now - 60 if expired else now + 3600,
        "role": role,
        "email": email,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _bearer(token: str) -> str:
    return f"Bearer {token}"


# ---------------------------------------------------------------------------
# FastAPI test app — wires a FakeSupabase factory so get_current_user can resolve
# the LOMAR role without a live database.
# ---------------------------------------------------------------------------

app = FastAPI()
register_exception_handlers(app)

app.state.supabase_factory = lambda _token: FakeSupabase(
    rows={
        "profiles": [
            {"id": "user-abc", "role": "customer"},
            {"id": "user-xyz", "role": "customer"},
            {"id": "u1", "role": "customer"},
            {"id": "jwt-user-123", "role": "customer"},
            {"id": "real-user", "role": "customer"},
        ]
    }
)


@app.get("/optional")
async def optional_route(user: CurrentUser = Depends(get_optional_user)):
    """Public-v1 style endpoint: anonymous-safe identity."""
    return {"user_id": user.id, "email": user.email, "role": user.role}


@app.get("/protected")
async def protected_route(user: CurrentUser = Depends(get_current_user)):
    """Protected endpoint: must have a valid token; role resolved from DB."""
    return {"user_id": user.id, "email": user.email, "role": user.role}


client = TestClient(app)


@pytest.fixture(autouse=True)
def _env():
    with patch.dict(
        os.environ,
        {"SUPABASE_JWT_SECRET": SECRET, "SUPABASE_JWT_AUDIENCE": AUDIENCE},
    ):
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Valid JWT
# ---------------------------------------------------------------------------


class TestValidJWT:
    def test_authenticated_user_extracted(self):
        token = _token(sub="user-abc", email="a@b.com", role="vendor")
        resp = client.get("/protected", headers={"authorization": _bearer(token)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-abc"
        assert data["email"] == "a@b.com"

    def test_optional_route_returns_identity(self):
        token = _token(sub="user-xyz")
        resp = client.get("/optional", headers={"authorization": _bearer(token)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-xyz"
        assert data["email"] == "user@example.com"
        # Optional auth does not read the JWT role claim; role stays empty.
        assert data["role"] == ""

    def test_authenticated_user_representation_is_consistent(self):
        """The same token always yields the same CurrentUser fields."""
        token = _token(sub="u1", email="e1@b.com", role="admin")
        first = client.get("/optional", headers={"authorization": _bearer(token)}).json()
        second = client.get("/optional", headers={"authorization": _bearer(token)}).json()
        assert first == second == {"user_id": "u1", "email": "e1@b.com", "role": ""}


# ---------------------------------------------------------------------------
# Missing JWT -> 401
# ---------------------------------------------------------------------------


class TestMissingJWT:
    def test_no_header(self):
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

    def test_empty_authorization_header(self):
        resp = client.get("/protected", headers={"authorization": ""})
        assert resp.status_code == 401

    def test_optional_route_degrades_to_anonymous(self):
        resp = client.get("/optional")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == ""


# ---------------------------------------------------------------------------
# Malformed JWT -> 401
# ---------------------------------------------------------------------------


class TestMalformedJWT:
    def test_not_a_jwt(self):
        resp = client.get("/protected", headers={"authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 401

    def test_empty_bearer_token(self):
        resp = client.get("/protected", headers={"authorization": "Bearer "})
        assert resp.status_code == 401

    def test_wrong_scheme(self):
        resp = client.get("/protected", headers={"authorization": "Token abc123"})
        assert resp.status_code == 401

    def test_bearer_with_garbage(self):
        resp = client.get("/protected", headers={"authorization": "Bearer ???.???.???"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Expired / invalid JWT -> 401
# ---------------------------------------------------------------------------


class TestExpiredInvalidJWT:
    def test_expired_token(self):
        token = _token(expired=True)
        resp = client.get("/protected", headers={"authorization": _bearer(token)})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

    def test_invalid_signature(self):
        token = _token(secret="not-the-real-secret")
        resp = client.get("/protected", headers={"authorization": _bearer(token)})
        assert resp.status_code == 401

    def test_wrong_audience(self):
        token = _token(bad_aud=True)
        resp = client.get("/protected", headers={"authorization": _bearer(token)})
        assert resp.status_code == 401

    def test_missing_sub_claim(self):
        now = int(time.time())
        payload = {"aud": AUDIENCE, "exp": now + 3600, "role": "customer"}
        token = jwt.encode(payload, SECRET, algorithm="HS256")
        resp = client.get("/protected", headers={"authorization": _bearer(token)})
        assert resp.status_code == 401

    def test_missing_exp_claim(self):
        payload = {"sub": "user-abc", "aud": AUDIENCE, "role": "customer"}
        token = jwt.encode(payload, SECRET, algorithm="HS256")
        resp = client.get("/protected", headers={"authorization": _bearer(token)})
        assert resp.status_code == 401

    def test_unconfigured_secret(self):
        """Fail-closed: an empty JWT secret must yield 401, not 500."""
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": ""}):
            get_settings.cache_clear()
            token = _token()
            resp = client.get("/protected", headers={"authorization": _bearer(token)})
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "unauthenticated"
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Authenticated-user extraction
# ---------------------------------------------------------------------------


class TestAuthenticatedUserExtraction:
    def test_user_id_comes_from_jwt_sub_not_body(self):
        """Identity must come from the validated JWT, never the request body.

        The protected endpoint reads user_id solely from the CurrentUser
        produced by get_current_user, so any body fields are irrelevant.
        """
        token = _token(sub="jwt-user-123", email="jwt@example.com")
        resp = client.get("/protected", headers={"authorization": _bearer(token)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "jwt-user-123"
        assert data["email"] == "jwt@example.com"

    def test_user_id_comes_from_jwt_not_header(self):
        """Arbitrary identity headers must be ignored."""
        token = _token(sub="real-user")
        resp = client.get(
            "/protected",
            headers={
                "authorization": _bearer(token),
                "x-user-id": "fake-user",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "real-user"

    def test_email_claim_populated(self):
        token = _token(sub="u1", email="claimed@example.com")
        resp = client.get("/optional", headers={"authorization": _bearer(token)})
        assert resp.status_code == 200
        assert resp.json()["email"] == "claimed@example.com"

    def test_role_claim_not_surfaced_by_current_user(self):
        """Optional authentication intentionally ignores the JWT role claim.

        The LOMAR role is resolved from the database by get_current_user, never
        from the token. The optional route therefore reports no role.
        """
        token = _token(sub="u1", role="admin")
        resp = client.get("/optional", headers={"authorization": _bearer(token)})
        assert resp.status_code == 200
        assert resp.json()["role"] == ""

    def test_role_resolved_from_db_by_require_user(self):
        """get_current_user resolves the authoritative LOMAR role from the DB."""
        token = _token(sub="user-abc")
        resp = client.get("/protected", headers={"authorization": _bearer(token)})
        assert resp.status_code == 200
        assert resp.json()["role"] == "customer"
