"""Role authorization, deliberately separate from JWT authentication."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends

from app.auth.dependencies import get_current_user
from app.auth.models import CurrentUser
from app.errors import ForbiddenError


def require_role(required_role: str) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    async def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role != required_role:
            raise ForbiddenError("Insufficient permissions.")
        return user

    return checker


def require_roles(*allowed_roles: str) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """Require one of several authoritative application roles."""
    allowed = frozenset(allowed_roles)

    async def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed:
            raise ForbiddenError("Insufficient permissions.")
        return user

    return checker


require_customer = require_role("customer")
require_vendor = require_role("vendor")
require_admin = require_role("admin")
require_business = require_roles("vendor", "admin")
