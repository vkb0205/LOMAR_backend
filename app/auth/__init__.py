"""Central authentication and authorization boundary for the LOMAR API."""

from .dependencies import get_current_user, get_optional_user
from .models import CurrentUser
from .permissions import (
    require_admin,
    require_business,
    require_customer,
    require_role,
    require_roles,
    require_vendor,
)

__all__ = [
    "CurrentUser",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "require_business",
    "require_customer",
    "require_role",
    "require_roles",
    "require_vendor",
]
