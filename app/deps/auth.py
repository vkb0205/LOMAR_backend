"""Authentication and authorization dependencies.

Fast-path ``current_user``:
    Extracts the ``sub`` claim from a verified Supabase JWT (HS256, ``aud``
    checked against ``SUPABASE_JWT_AUDIENCE``, ``exp`` rejected).  **Does not**
    open any database connection — it is a pure-JWT, O(1) operation suitable
    for every endpoint call.  Exposes ``user_id`` and optional ``role`` claims
    already present in the token (role is *informational only*).

``require_admin``:
    Calls the fast-path ``current_user`` first, then performs a **fresh**
    backend lookup of ``profiles.role == 'admin'`` via the caller-JWT client
    bound to ``request.state`` (set by the auth middleware below).
    Never trusts JWT role claims directly (see plan.md Constitution Check
    note and research.md R6).
"""

from __future__ import annotations

import logging
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.config import get_settings
from app.deps.db import get_supabase
from app.errors import DatabaseUnavailableError, UnauthenticatedError, ForbiddenError

logger = logging.getLogger("app.auth")


class TokenPayload(BaseModel):
    """Minimal verified JWT body."""

    sub: str
    aud: str | None = None
    exp: int | None = None
    role: str | None = None  # informational only; not trusted for require_admin


class AuthenticatedUser(BaseModel):
    """The caller identity attached to every non-anonymous request."""

    user_id: str
    role: str | None = None


# ---------------------------------------------------------------------------
# Low-level token helpers (no DB access)
# ---------------------------------------------------------------------------

def _decode_token(token: str) -> TokenPayload:
    """Verify a Supabase HS256 JWT and return its claims.

    Raises ``jwt.PyJWTError`` (wrapped by callers into 401) on any failure.
    """
    settings = get_settings()
    secret = settings.supabase_jwt_secret
    if secret == "":
        raise UnauthenticatedError("JWT verification is not configured.")
    try:
        decoded = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience,
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("Token expired.") from exc
    except jwt.PyJWTError as exc:
        raise UnauthenticatedError(f"Invalid token: {exc}") from exc
    return TokenPayload.model_validate(decoded)


def _extract_bearer(request: Request) -> str:
    """Pull the Bearer token from the Authorization header.

    Returns an empty string when the header is missing or malformed.
    """
    auth_header = (request.headers.get("authorization") or "").strip()
    if not auth_header:
        return ""
    if not auth_header.lower().startswith("bearer "):
        return ""
    return auth_header[7:].strip()


# ---------------------------------------------------------------------------
# Fast-path identity: sub only, no DB round-trip
# ---------------------------------------------------------------------------

async def current_user(request: Request) -> AuthenticatedUser:
    """Extract the caller's user id from the JWT.

    Returns ``user_id=""`` when the request is unauthenticated so that routers
    branching on ``ENABLE_AUTH`` can treat the absence uniformly.
    """
    token = _extract_bearer(request)
    if token == "":
        return AuthenticatedUser(user_id="")
    try:
        payload = _decode_token(token)
    except UnauthenticatedError:
        return AuthenticatedUser(user_id="")
    return AuthenticatedUser(user_id=payload.sub, role=payload.role)


async def require_user(
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AuthenticatedUser:
    """Verify that a valid token with a ``sub`` is present.

    Used by endpoints that MUST NOT accept anonymous callers regardless of
    ``ENABLE_AUTH`` (e.g. ``/api/v1/me/*`` and ``/api/v1/admin/*``).
    """
    if user.user_id == "":
        raise UnauthenticatedError("Authentication required.")
    return user


async def require_admin(
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    request: Request,
) -> AuthenticatedUser:
    """Verify the caller is a platform admin via a fresh backend lookup.

    1. Requires an authenticated user (raises 401 when anonymous).
    2. Resolves the caller-JWT Supabase client through ``get_supabase`` so the
       middleware-bound client, the test/embedded factory, and the live
       anon-key path all behave identically.
    3. Reads ``profiles.role`` with ``eq(id, caller.sub)``.
    4. Returns 403 when the caller is authenticated but not an admin, and
       503 ``database_unavailable`` when the lookup itself cannot complete —
       an unreachable database is never reported as "forbidden".

    The profile row **must exist** because ``auth.uid()`` is the FK target
    in ``profiles`` (see migration 20260726000100).
    """
    # Explicit guard so this function is safe even when called directly
    # (bypassing FastAPI's ``Depends(require_user)`` chain).
    if user.user_id == "":
        raise UnauthenticatedError("Authentication required.")

    admin_client = getattr(request.state, "supabase", None)
    if admin_client is None:
        # Falls back to the app's configured factory / anon client; raises
        # DatabaseUnavailableError when Supabase is not configured at all.
        admin_client = await get_supabase(request)

    try:
        result = (
            await admin_client.table("profiles")
            .select("role")
            .eq("id", user.user_id)
            .single()
            .execute()
        )
    except DatabaseUnavailableError:
        # Propagate as 503 — the caller may well be an admin; we simply
        # cannot tell right now (Constitution V, SC-005).
        raise
    except Exception as exc:
        logger.warning("admin_profile_lookup_failed user_id=%s", user.user_id)
        raise ForbiddenError("Unable to verify admin status.") from exc

    rows = getattr(result, "data", None) or {}
    role: str | None = rows.get("role") if isinstance(rows, dict) else None
    if role != "admin":
        raise ForbiddenError("Admin access required.")
    return AuthenticatedUser(user_id=user.user_id, role="admin")
