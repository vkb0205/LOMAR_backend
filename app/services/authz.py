"""Backend-verified LOMAR application-role resolution.

The LOMAR application role (``profiles.role``) is independent of the
authentication provider.  It is the authoritative source for authorization
decisions and is resolved through a **fresh** ``profiles`` lookup on every
request — never from the JWT ``role`` claim (R6) or any client-supplied value.

Supported roles:
    customer — authenticated customer (couple / planner)
    vendor   — vendor owner/administrator
    admin    — platform administrator

``resolve_lomar_role`` reads ``profiles.role`` and fails **closed** to
``'customer'`` on any missing row or lookup failure — the least privileged role.
"""

from __future__ import annotations

import logging
from typing import Any

from app.deps.db import run_db, unwrap

logger = logging.getLogger("app.services.authz")

# --- LOMAR application-role enum -------------------------------------------------

LOMAR_ROLE_CUSTOMER = "customer"
LOMAR_ROLE_VENDOR = "vendor"
LOMAR_ROLE_ADMIN = "admin"

LOMAR_ROLES = frozenset({LOMAR_ROLE_CUSTOMER, LOMAR_ROLE_VENDOR, LOMAR_ROLE_ADMIN})
LOMAR_DEFAULT_ROLE = LOMAR_ROLE_CUSTOMER


def normalize_lomar_role(value: Any) -> str:
    """Coerce an arbitrary value to a valid LOMAR role.

    Anything not in the known enum (NULL, '', typos, legacy provider values)
    collapses to ``'customer'`` — fail closed to the least privileged role.
    """
    return value if value in LOMAR_ROLES else LOMAR_DEFAULT_ROLE


async def resolve_lomar_role(
    client: Any, user_id: str, *, default: str | None = LOMAR_DEFAULT_ROLE
) -> str | None:
    """Read the authoritative LOMAR role from ``profiles.role``.

    Performs a fresh DB lookup; never trusts the JWT claim or any client value.
    Fails closed to ``'customer'`` when the row is missing or the lookup errors —
    an unresolved role never escalates privilege.
    """
    if not user_id:
        return default
    try:
        result = await run_db(
            lambda: client.table("profiles")
            .select("role")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception:
        logger.warning("lomar_role_lookup_failed user_id=%s", user_id)
        return default
    row = unwrap(result)
    if isinstance(row, dict):
        return normalize_lomar_role(row.get("role"))
    rows = row or []
    if not rows:
        return default
    value = rows[0].get("role")
    return normalize_lomar_role(value) if value is not None else default


async def is_platform_admin(client: Any, user_id: str) -> bool:
    """Fresh ``profiles.role == 'admin'`` lookup; failure denies.

    Reimplemented over ``resolve_lomar_role`` so the single source of truth for
    role resolution is shared across all authorization checks.
    """
    return await resolve_lomar_role(client, user_id) == LOMAR_ROLE_ADMIN
