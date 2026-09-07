"""Chat repositories — thread ownership is always checked with ID + user ID."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import AsyncClient

from app.deps.db import run_db, unwrap, unwrap_one
from app.errors import NotFoundError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_thread(client: AsyncClient, thread_id: str, user_id: str) -> dict[str, Any] | None:
    result = await run_db(
        lambda: client.table("chat_threads")
        .select("*")
        .eq("id", thread_id)
        .eq("user_id", user_id)
        .execute()
    )
    rows = unwrap(result) or []
    return rows[0] if rows else None


async def list_threads(
    client: AsyncClient,
    user_id: str,
    context_type: str | None = None,
) -> list[dict[str, Any]]:
    """List the caller's chat threads, optionally filtered by context type."""
    query = client.table("chat_threads").select("*").eq("user_id", user_id)
    if context_type:
        query = query.eq("context_type", context_type)
    result = await run_db(lambda: query.execute())
    rows = unwrap(result) or []
    return sorted(rows, key=lambda row: (row.get("updated_at") or "", str(row.get("id", ""))), reverse=True)


async def create_thread(client: AsyncClient, user_id: str, payload: dict[str, Any]) -> str:
    row = {
        "user_id": user_id,
        "context_type": payload.get("contextType") or "general",
        "vendor_id": payload.get("vendorId"),
        "service_id": payload.get("serviceId"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    result = await run_db(lambda: client.table("chat_threads").insert(row).select("id").execute())
    created = unwrap_one(result) or {}
    return str(created.get("id", row.get("id", "")))


async def list_messages(client: AsyncClient, thread_id: str, user_id: str) -> list[dict[str, Any]]:
    if await get_thread(client, thread_id, user_id) is None:
        raise NotFoundError()
    result = await run_db(
        lambda: client.table("chat_messages")
        .select("*")
        .eq("thread_id", thread_id)
        .eq("user_id", user_id)
        .execute()
    )
    rows = unwrap(result) or []
    return sorted(rows, key=lambda row: (row.get("created_at") or "", str(row.get("id", ""))))


async def add_message(
    client: AsyncClient,
    *,
    thread_id: str,
    user_id: str,
    role: str,
    content: str,
    suggested_service_id: str | None = None,
) -> dict[str, Any]:
    row = {
        "thread_id": thread_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "suggested_service_id": suggested_service_id,
        "created_at": _now(),
    }
    result = await run_db(lambda: client.table("chat_messages").insert(row).select("*").execute())
    return unwrap_one(result) or row

