"""Unit tests for the monotonic customer/vendor/admin role hierarchy."""

from __future__ import annotations

import pytest

from app.auth.models import CurrentUser
from app.auth.permissions import (
    require_admin,
    require_customer,
    require_minimum_role,
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
        (require_vendor, "admin", True),
        (require_admin, "customer", False),
        (require_admin, "vendor", False),
        (require_admin, "admin", True),
        (require_customer, "unknown", False),
    ],
)
async def test_role_hierarchy(dependency, role: str, allowed: bool) -> None:
    user = CurrentUser(id="actor", role=role)
    if allowed:
        assert await dependency(user) is user
    else:
        with pytest.raises(ForbiddenError):
            await dependency(user)


def test_unknown_minimum_role_is_rejected_at_configuration_time() -> None:
    with pytest.raises(ValueError, match="Unknown minimum role"):
        require_minimum_role("business")
