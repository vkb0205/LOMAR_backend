"""Backend-verified admin check reusable by non-admin routers.

`AuthenticatedUser.role` carries the JWT's own `role` claim, which R6
forbids as an authorization source. Any endpoint that grants extra power to
admins (e.g. social moderation) must resolve the flag through a fresh
`profiles.role` lookup instead.
"""

from __future__ import annotations

import logging
from typing import Any

from app.deps.db import run_db, unwrap

logger = logging.getLogger("app.services.authz")


async def is_platform_admin(client: Any, user_id: str) -> bool:
    """Fresh `profiles.role == 'admin'` lookup; failure denies (fail closed)."""
    if not user_id:
        return False
    try:
        result = await run_db(
            lambda: client.table("profiles").select("role").eq("id", user_id).execute()
        )
    except Exception:
        logger.warning("admin_lookup_failed user_id=%s", user_id)
        return False
    rows = unwrap(result) or []
    return bool(rows) and rows[0].get("role") == "admin"
