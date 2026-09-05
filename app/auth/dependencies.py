"""FastAPI authentication dependencies; public routes opt in to optional auth."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import verify_supabase_jwt
from app.auth.models import AuthenticatedIdentity, CurrentUser
from app.deps.db import get_supabase
from app.errors import ForbiddenError, UnauthenticatedError
from app.services.authz import resolve_lomar_role

bearer = HTTPBearer(auto_error=False)
OptionalCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def _identity(credentials: HTTPAuthorizationCredentials | None) -> AuthenticatedIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthenticatedError("Authentication required.")
    payload = verify_supabase_jwt(credentials.credentials)
    return AuthenticatedIdentity(id=payload["sub"], email=payload.get("email"))


async def get_optional_user(request: Request, credentials: OptionalCredentials) -> CurrentUser:
    """Anonymous-safe identity for routes explicitly declared public."""
    request.state.access_token = ""
    request.state.user_id = ""
    if credentials is None:
        return CurrentUser(id="", role="")
    try:
        identity = _identity(credentials)
    except UnauthenticatedError:
        return CurrentUser(id="", role="")
    request.state.access_token = credentials.credentials
    request.state.user_id = identity.id
    return CurrentUser(id=identity.id, email=identity.email, role="")


async def get_current_user(request: Request, credentials: OptionalCredentials) -> CurrentUser:
    """Authenticate the caller and load the authoritative role from profiles."""
    identity = _identity(credentials)
    request.state.access_token = credentials.credentials
    request.state.user_id = identity.id
    client = await get_supabase(request)
    role = await resolve_lomar_role(client, identity.id, default=None)
    if role is None:
        raise ForbiddenError("LOMAR profile not found.")
    return CurrentUser(id=identity.id, email=identity.email, role=role)
