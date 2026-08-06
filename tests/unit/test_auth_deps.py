"""T012 — auth dependency unit tests (research.md R6, FR-005).

`tests/unit/test_auth.py` covers token decoding and the basic
`require_admin` accept/reject paths. This file covers the properties T012
calls out explicitly and that are easy to regress:

* expired token -> 401
* valid token -> `sub` resolved
* non-admin -> 403 from `require_admin`
* a role change in the DB *after* token issuance is respected, i.e. the JWT
  `role` claim is never the authorization source
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from app.deps.auth import current_user, require_admin, require_user
from app.errors import ForbiddenError, UnauthenticatedError
from tests.conftest import TEST_ADMIN_ID, TEST_USER_ID, factory_token


def _request(token: str | None = None, *, supabase=None) -> Request:
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/admin/overview",
            "headers": headers,
            "query_string": b"",
        }
    )
    request.state.supabase = supabase
    return request


def _profiles_returning(role: str | None):
    """Build a Supabase client mock whose profiles lookup returns *role*."""
    execute = AsyncMock(return_value=MagicMock(data={"role": role} if role else {}))
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.execute = execute
    client = MagicMock()
    client.table = MagicMock(return_value=chain)
    return client


class TestTokenResolution:
    @pytest.mark.asyncio
    async def test_valid_token_resolves_sub(self):
        user = await current_user(_request(factory_token(TEST_USER_ID)))
        assert user.user_id == TEST_USER_ID

    @pytest.mark.asyncio
    async def test_expired_token_is_anonymous_then_401(self, expired_token):
        user = await current_user(_request(expired_token))
        assert user.user_id == ""
        with pytest.raises(UnauthenticatedError):
            await require_user(user)

    @pytest.mark.asyncio
    async def test_wrong_secret_is_rejected(self):
        bad = factory_token(TEST_USER_ID, secret="not-the-real-secret")
        user = await current_user(_request(bad))
        assert user.user_id == ""

    @pytest.mark.asyncio
    async def test_missing_header_is_anonymous(self):
        user = await current_user(_request(None))
        assert user.user_id == ""


class TestRequireAdminFreshLookup:
    @pytest.mark.asyncio
    async def test_non_admin_profile_returns_403(self):
        token = factory_token(TEST_USER_ID, role="customer")
        request = _request(token, supabase=_profiles_returning("customer"))
        user = await current_user(request)
        with pytest.raises(ForbiddenError):
            await require_admin(user, request)

    @pytest.mark.asyncio
    async def test_admin_profile_accepted(self):
        token = factory_token(TEST_ADMIN_ID, role="admin")
        request = _request(token, supabase=_profiles_returning("admin"))
        user = await current_user(request)
        resolved = await require_admin(user, request)
        assert resolved.user_id == TEST_ADMIN_ID
        assert resolved.role == "admin"

    @pytest.mark.asyncio
    async def test_jwt_role_admin_but_db_says_customer_is_403(self):
        """R6: the JWT `role` claim is never the authorization source.

        Simulates a user whose token was issued while they were an admin and
        whose `profiles.role` has since been downgraded.
        """
        token = factory_token(TEST_ADMIN_ID, role="admin")  # stale claim
        request = _request(token, supabase=_profiles_returning("customer"))
        user = await current_user(request)
        assert user.role == "admin"  # claim present...
        with pytest.raises(ForbiddenError):  # ...but ignored
            await require_admin(user, request)

    @pytest.mark.asyncio
    async def test_jwt_role_customer_but_db_says_admin_is_allowed(self):
        """Inverse of the above: a promotion is picked up without re-login."""
        token = factory_token(TEST_USER_ID, role="customer")
        request = _request(token, supabase=_profiles_returning("admin"))
        user = await current_user(request)
        resolved = await require_admin(user, request)
        assert resolved.role == "admin"

    @pytest.mark.asyncio
    async def test_missing_profile_row_returns_403(self):
        token = factory_token(TEST_USER_ID)
        request = _request(token, supabase=_profiles_returning(None))
        user = await current_user(request)
        with pytest.raises(ForbiddenError):
            await require_admin(user, request)

    @pytest.mark.asyncio
    async def test_anonymous_raises_401_not_403(self):
        request = _request(None, supabase=_profiles_returning("admin"))
        user = await current_user(request)
        with pytest.raises(UnauthenticatedError):
            await require_admin(user, request)

    @pytest.mark.asyncio
    async def test_lookup_failure_does_not_grant_access(self):
        """A failed lookup must fail closed, never fall through to admin."""
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute = AsyncMock(side_effect=RuntimeError("postgrest exploded"))
        client = MagicMock()
        client.table = MagicMock(return_value=chain)

        token = factory_token(TEST_USER_ID)
        request = _request(token, supabase=client)
        user = await current_user(request)
        with pytest.raises(ForbiddenError):
            await require_admin(user, request)
