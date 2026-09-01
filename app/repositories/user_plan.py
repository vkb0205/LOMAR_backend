"""User wedding-plan repository (feature 003).

Every write is scoped by caller ``user_id`` (from the verified JWT, never the
request body) and by ``item_type``, mirroring the dashboard repositories.

Upserts rely on the partial unique indexes ``(user_id, service_id)`` and
``(user_id, plan_id)`` on ``user_plan_items`` (migration
20260901000300_user_plan_acceptance.sql) for idempotent last-write-wins.

Reads go through the security-invoker view ``v_user_accepted_plan``, which
returns only ``status = 'accepted'`` rows and inherits the caller's RLS, so the
same client that could not write another user's row also cannot read it.
"""

from __future__ import annotations

from typing import Any, Literal

from supabase import AsyncClient

from app.deps.db import run_db, unwrap
from app.errors import NotFoundError


async def get_service(client: AsyncClient, service_id: str) -> dict[str, Any] | None:
    """Return an active catalog service, or None (covers 404/422 unknown item)."""
    result = await run_db(
        lambda: client.table("services")
        .select("id")
        .eq("id", service_id)
        .eq("status", "active")
        .execute()
    )
    rows = unwrap(result) or []
    return rows[0] if rows else None


async def get_wedding_plan(client: AsyncClient, plan_id: str) -> dict[str, Any] | None:
    """Return an active wedding plan, or None (covers 404/422 unknown item)."""
    result = await run_db(
        lambda: client.table("wedding_plans")
        .select("id")
        .eq("id", plan_id)
        .eq("status", "active")
        .execute()
    )
    rows = unwrap(result) or []
    return rows[0] if rows else None


async def upsert_plan_item(
    client: AsyncClient,
    *,
    user_id: str,
    item_type: Literal["service", "plan"],
    item_id: str,
    status: Literal["accepted", "declined", "removed"],
    accepted_at: str | None,
    updated_at: str | None = None,
) -> None:
    """Upsert a user's decision about one item — last write wins (FR-004).

    ``service_id`` and ``plan_id`` are separate columns, so the item id is
    routed to the correct one by ``item_type`` and the matching partial unique
    index makes re-accepting idempotent.
    """
    if item_type == "service":
        if await get_service(client, item_id) is None:
            raise NotFoundError("Unknown service.")
        ref = {"service_id": item_id, "plan_id": None}
        on_conflict = "user_id,service_id"
    else:
        if await get_wedding_plan(client, item_id) is None:
            raise NotFoundError("Unknown wedding plan.")
        ref = {"plan_id": item_id, "service_id": None}
        on_conflict = "user_id,plan_id"

    payload = {
        "user_id": user_id,
        "item_type": item_type,
        "status": status,
        "accepted_at": accepted_at,
        "updated_at": updated_at or accepted_at,
        **ref,
    }
    await run_db(
        lambda: client.table("user_plan_items")
        .upsert(payload, on_conflict=on_conflict)
        .execute()
    )


_VIEW_FIELDS = (
    "user_id",
    "item_type",
    "category",
    "service_id",
    "service_name",
    "service_price",
    "plan_id",
    "plan_name",
    "accepted_at",
)


async def list_accepted_plan(client: AsyncClient, user_id: str) -> list[dict[str, Any]]:
    """Return the caller's accepted-plan rows via the view (accepted only).

    The view is security-invoker and owner-filtered by RLS; ``user_id`` is
    also passed as an explicit filter for defense in depth and to keep parity
    with the other repository reads.
    """
    result = await run_db(
        lambda: client.table("v_user_accepted_plan")
        .select(",".join(_VIEW_FIELDS))
        .eq("user_id", user_id)
        .order("category", desc=False)
        .execute()
    )
    rows = unwrap(result) or []
    return [{k: row.get(k) for k in _VIEW_FIELDS if row.get(k) is not None} for row in rows]


async def accepted_plan_summary(client: AsyncClient, user_id: str) -> list[dict[str, Any]]:
    """Group the caller's accepted plan by category with counts (no PII).

    Returns a compact ``[{category, count}]`` list used as consult context and
    by the agent's ``get_user_plan`` tool. Category is derived in the view.
    """
    rows = await list_accepted_plan(client, user_id)
    counts: dict[str, int] = {}
    for row in rows:
        category = row.get("category") or "Khác"
        counts[category] = counts.get(category, 0) + 1
    return [{"category": category, "count": count} for category, count in counts.items()]
