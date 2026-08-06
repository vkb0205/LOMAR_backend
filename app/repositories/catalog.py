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


async def list_service_images(client: AsyncClient) -> list[dict[str, Any]]:
    result = await run_db(lambda: client.table("service_images").select("*").execute())
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
