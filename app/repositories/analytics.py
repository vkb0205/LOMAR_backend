"""Analytics repositories.

Service-role justification (Constitution II, research.md R2):
`get_admin_website_analytics` aggregates cross-user `analytics_page_views`
rows and its RPC is admin-only; `record_page_*` are security-definer public
RPCs with no natural owner. The service-role client is used only for the
admin aggregate. Public tracking uses the caller/anon client so RPC grants
and `auth.uid()` attribution remain intact.
"""

from __future__ import annotations

from typing import Any

from supabase import AsyncClient

from app.deps.db import run_db, unwrap


async def record_page_view(client: AsyncClient, params: dict[str, Any]) -> Any:
    result = await run_db(lambda: client.rpc("record_page_view", params).execute())
    return unwrap(result)


async def record_page_engagement(client: AsyncClient, params: dict[str, Any]) -> Any:
    result = await run_db(lambda: client.rpc("record_page_engagement", params).execute())
    return unwrap(result)


async def get_admin_website_analytics(client: AsyncClient, days: int) -> dict[str, Any]:
    # Service-role is required here: the RPC aggregates all visitor rows, which
    # caller-JWT RLS intentionally cannot read. require_admin gates the route.
    result = await run_db(
        lambda: client.rpc("get_admin_website_analytics", {"p_days": days}).execute()
    )
    return unwrap(result) or {}
