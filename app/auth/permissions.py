"""Authenticated-user and exact-role authorization groups.

Customer access is the universal baseline for every authenticated LOMAR user.
Business and admin access remain independent, exact-role tiers.
"""

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

_KNOWN_ROLES = frozenset({LOMAR_ROLE_CUSTOMER, LOMAR_ROLE_VENDOR, LOMAR_ROLE_ADMIN})


async def require_authenticated(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Allow any authenticated LOMAR user, independent of application role."""
    return user


def require_exact_role(
    required_role: str,
) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """Require the caller to hold exactly ``required_role`` (no inheritance)."""
    if required_role not in _KNOWN_ROLES:
        raise ValueError(f"Unknown role: {required_role}")

    async def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role != required_role:
            raise ForbiddenError("Insufficient permissions.")
        return user

    return checker


# ``customer`` is the product name for the universal authenticated surface.
# Authentication and profile resolution have already happened in
# ``get_current_user`` before this dependency runs.
require_customer = require_authenticated
require_vendor = require_exact_role(LOMAR_ROLE_VENDOR)
require_admin = require_exact_role(LOMAR_ROLE_ADMIN)
