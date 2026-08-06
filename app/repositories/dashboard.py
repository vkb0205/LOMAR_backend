"""Dashboard repository — every read/write is scoped by caller `user_id`
(from the verified JWT, never the request body) per data-model.md invariant 1.

Upserts rely on the existing composite unique constraints
`(user_id, task_id)` on `user_journey_tasks` and `(user_id, voucher_id)` on
`user_vouchers` (research.md R8) — verified against migrate_to_v2.sql
(primary key user_id, task_id / user_id, voucher_id).
"""

from __future__ import annotations

from typing import Any

from supabase import AsyncClient

from app.deps.db import run_db, unwrap
from app.errors import NotFoundError


async def list_journey_tasks(client: AsyncClient) -> list[dict[str, Any]]:
    result = await run_db(
        lambda: client.table("journey_tasks").select("*").eq("active", True).execute()
    )
    return unwrap(result) or []


async def list_user_journey_tasks(client: AsyncClient, user_id: str) -> list[dict[str, Any]]:
    result = await run_db(
        lambda: client.table("user_journey_tasks").select("*").eq("user_id", user_id).execute()
    )
    return unwrap(result) or []


async def list_vouchers(client: AsyncClient) -> list[dict[str, Any]]:
    result = await run_db(lambda: client.table("vouchers").select("*").eq("active", True).execute())
    return unwrap(result) or []


async def list_user_vouchers(client: AsyncClient, user_id: str) -> list[dict[str, Any]]:
    result = await run_db(
        lambda: client.table("user_vouchers").select("*").eq("user_id", user_id).execute()
    )
    return unwrap(result) or []


async def list_saved_designs(client: AsyncClient, user_id: str) -> list[dict[str, Any]]:
    result = await run_db(
        lambda: client.table("ai_design_projects")
        .select("id, title, category, status, created_at")
        .eq("user_id", user_id)
        .execute()
    )
    return unwrap(result) or []


async def get_journey_task(client: AsyncClient, task_id: str) -> dict[str, Any] | None:
    result = await run_db(
        lambda: client.table("journey_tasks").select("*").eq("id", task_id).execute()
    )
    rows = unwrap(result) or []
    return rows[0] if rows else None


async def get_voucher(client: AsyncClient, voucher_id: str) -> dict[str, Any] | None:
    result = await run_db(
        lambda: client.table("vouchers").select("*").eq("id", voucher_id).execute()
    )
    rows = unwrap(result) or []
    return rows[0] if rows else None


async def upsert_user_journey_task(
    client: AsyncClient,
    *,
    user_id: str,
    task_id: str,
    status: str,
    completed_at: str | None,
    updated_at: str,
) -> None:
    """Upsert on `(user_id, task_id)` — last commit wins (R8)."""
    task = await get_journey_task(client, task_id)
    if task is None:
        raise NotFoundError("Unknown journey task.")
    payload = {
        "user_id": user_id,
        "task_id": task_id,
        "status": status,
        "completed_at": completed_at,
        "updated_at": updated_at,
    }
    await run_db(
        lambda: client.table("user_journey_tasks")
        .upsert(payload, on_conflict="user_id,task_id")
        .execute()
    )


async def upsert_user_voucher(
    client: AsyncClient,
    *,
    user_id: str,
    voucher_id: str,
    status: str,
    unlocked_at: str | None,
) -> None:
    """Upsert on `(user_id, voucher_id)` — last commit wins (R8)."""
    voucher = await get_voucher(client, voucher_id)
    if voucher is None:
        raise NotFoundError("Unknown voucher.")
    payload = {
        "user_id": user_id,
        "voucher_id": voucher_id,
        "status": status,
        "unlocked_at": unlocked_at,
    }
    await run_db(
        lambda: client.table("user_vouchers")
        .upsert(payload, on_conflict="user_id,voucher_id")
        .execute()
    )
