"""Unit tests for universal customer access and exact privileged tiers."""

from __future__ import annotations

import pytest

from app.auth.models import CurrentUser
from app.auth.permissions import (
    require_admin,
    require_authenticated,
    require_customer,
    require_exact_role,
    require_vendor,
)
from app.errors import ForbiddenError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dependency", "role", "allowed"),
    [
        (require_customer, "customer", True),
        (require_customer, "vendor", True),
        (require_customer, "admin", True),
        (require_vendor, "customer", False),
        (require_vendor, "vendor", True),
        (require_vendor, "admin", False),
        (require_admin, "customer", False),
        (require_admin, "vendor", False),
        (require_admin, "admin", True),
    ],
)
async def test_permission_groups(dependency, role: str, allowed: bool) -> None:
    user = CurrentUser(id="actor", role=role)
    if allowed:
        assert await dependency(user) is user
    else:
        with pytest.raises(ForbiddenError):
            await dependency(user)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["customer", "vendor", "admin"])
async def test_authenticated_group_accepts_every_application_role(role: str) -> None:
    user = CurrentUser(id="actor", role=role)
    assert await require_authenticated(user) is user


def test_unknown_role_is_rejected_at_configuration_time() -> None:
    with pytest.raises(ValueError, match="Unknown role"):
        require_exact_role("business")
