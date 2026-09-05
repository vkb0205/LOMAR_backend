"""Catalog repository — caller-JWT client only (public reads, RLS preserved).

No service-role usage: every query here reads catalog-visible rows that the
anon role can already see under RLS (research.md R2).
"""

from __future__ import annotations

from typing import Any

from supabase import AsyncClient

from app.deps.db import run_db, unwrap

# Catalog visibility per data-model.md: only `active` vendors/services are
# exposed on public endpoints.
VENDOR_VISIBLE_STATUS = "active"
SERVICE_VISIBLE_STATUS = "active"


async def list_vendors(client: AsyncClient) -> list[dict[str, Any]]:
    result = await run_db(
        lambda: client.table("vendors")
        .select("*")
        .eq("status", VENDOR_VISIBLE_STATUS)
        .execute()
    )
    return unwrap(result) or []


async def get_vendor(client: AsyncClient, vendor_id: str) -> dict[str, Any] | None:
    result = await run_db(
        lambda: client.table("vendors")
        .select("*")
        .eq("id", vendor_id)
        .eq("status", VENDOR_VISIBLE_STATUS)
        .execute()
    )
    rows = unwrap(result) or []
    return rows[0] if rows else None


async def list_vendor_services(client: AsyncClient, vendor_id: str) -> list[dict[str, Any]]:
    result = await run_db(
        lambda: client.table("services")
        .select("*")
        .eq("vendor_id", vendor_id)
        .eq("status", SERVICE_VISIBLE_STATUS)
        .execute()
    )
    return unwrap(result) or []


async def list_services(client: AsyncClient) -> list[dict[str, Any]]:
    result = await run_db(
        lambda: client.table("services")
        .select("*")
        .eq("status", SERVICE_VISIBLE_STATUS)
        .execute()
    )
    return unwrap(result) or []


async def list_all_vendors_for_customize(client: AsyncClient) -> list[dict[str, Any]]:
    """Vendors referenced by the customize catalog.

    Mirrors the frontend's previous unfiltered `vendors` read, but keeps the
    public catalog-visibility filter so a suspended vendor cannot leak.
    """
    return await list_vendors(client)


async def get_service(client: AsyncClient, service_id: str) -> dict[str, Any] | None:
    result = await run_db(
        lambda: client.table("services")
        .select("*")
        .eq("id", service_id)
        .eq("status", SERVICE_VISIBLE_STATUS)
        .execute()
    )
    rows = unwrap(result) or []
    return rows[0] if rows else None


# --- Wedding plans (public, active-only reads) --------------------------------

WEDDING_PLAN_VISIBLE_STATUS = "active"
_PLAN_CARD_FIELDS = (
    "id",
    "name",
    "description",
    "style",
    "min_guests",
    "max_guests",
    "min_budget",
    "max_budget",
    "currency",
    "cover_image_url",
    "status",
)
_ITEM_FIELDS = ("id", "wedding_plan_id", "service_id", "role", "sort_order", "quantity", "unit_price", "currency")
_SERVICE_ITEM_FIELDS = ("id", "name", "category", "vendor_id")


async def list_wedding_plans(client: AsyncClient) -> list[dict[str, Any]]:
    """Return active wedding plans, cheapest-first by published min budget."""
    result = await run_db(
        lambda: client.table("wedding_plans")
        .select(",".join(_PLAN_CARD_FIELDS))
        .eq("status", WEDDING_PLAN_VISIBLE_STATUS)
        .order("min_budget", desc=False)
        .execute()
    )
    rows = unwrap(result) or []
    return [{k: row[k] for k in _PLAN_CARD_FIELDS if row.get(k) is not None} for row in rows]


async def get_wedding_plan(client: AsyncClient, plan_id: str) -> dict[str, Any] | None:
    """Return one active wedding plan, projection-only. Items fetched separately."""
    result = await run_db(
        lambda: client.table("wedding_plans")
        .select(",".join(_PLAN_CARD_FIELDS))
        .eq("id", plan_id)
        .eq("status", WEDDING_PLAN_VISIBLE_STATUS)
        .execute()
    )
    rows = unwrap(result) or []
    if not rows:
        return None
    return {k: rows[0][k] for k in _PLAN_CARD_FIELDS if rows[0].get(k) is not None}


async def list_wedding_plan_items(client: AsyncClient, plan_id: str) -> list[dict[str, Any]]:
    """Return a plan's items, each resolved to its catalog service id/name/vendor."""
    result = await run_db(
        lambda: client.table("wedding_plan_items")
        .select(
            ",".join(
                _ITEM_FIELDS
                + tuple(
                    f"services({col})" for col in _SERVICE_ITEM_FIELDS
                )
            )
        )
        .eq("wedding_plan_id", plan_id)
        .order("sort_order", desc=False)
        .execute()
    )
    rows = unwrap(result) or []
    # PostgREST embeds the join under a `services` key; normalize to the card
    # shape the router/schema expect.
    normalized: list[dict[str, Any]] = []
    for row in rows:
        item = {k: row.get(k) for k in _ITEM_FIELDS if row.get(k) is not None}
        service = row.get("services")
        if isinstance(service, list):
            service = service[0] if service else {}
        if isinstance(service, dict):
            item["service"] = {k: service.get(k) for k in _SERVICE_ITEM_FIELDS if service.get(k) is not None}
        normalized.append(item)
    return normalized
