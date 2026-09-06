"""Role authorization, deliberately separate from JWT authentication."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends

from app.auth.dependencies import get_current_user
from app.auth.models import CurrentUser
from app.errors import ForbiddenError
from app.services.authz import (
    LOMAR_ROLE_ADMIN,
    LOMAR_ROLE_CUSTOMER,
    LOMAR_ROLE_VENDOR,
)

_ROLE_LEVELS = {
    LOMAR_ROLE_CUSTOMER: 10,
    LOMAR_ROLE_VENDOR: 20,
    LOMAR_ROLE_ADMIN: 30,
}


def require_minimum_role(
    minimum_role: str,
) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """Require a role at or above ``minimum_role`` in the LOMAR hierarchy."""
    try:
        minimum_level = _ROLE_LEVELS[minimum_role]
    except KeyError as exc:
        raise ValueError(f"Unknown minimum role: {minimum_role}") from exc

    async def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if _ROLE_LEVELS.get(user.role, -1) < minimum_level:
            raise ForbiddenError("Insufficient permissions.")
        return user

    return checker


require_customer = require_minimum_role(LOMAR_ROLE_CUSTOMER)
require_vendor = require_minimum_role(LOMAR_ROLE_VENDOR)
require_admin = require_minimum_role(LOMAR_ROLE_ADMIN)
