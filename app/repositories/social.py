"""Social repositories — caller JWT by default; no client-supplied owner IDs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import AsyncClient

from app.deps.db import run_db, unwrap


async def _select_filtered(
    client: AsyncClient,
    table: str,
    filters: list[tuple[str, Any]],
    columns: str = "*",
) -> list[dict[str, Any]]:
    def build():
        query = client.table(table).select(columns)
        for column, value in filters:
            query = query.eq(column, value)
        return query.execute()

    result = await run_db(build)
    return unwrap(result) or []


async def list_visible_posts(client: AsyncClient) -> list[dict[str, Any]]:
    rows = await _select_filtered(client, "posts", [("status", "published")])
    return sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)


async def profiles_by_ids(client: AsyncClient, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    result = await run_db(lambda: client.table("profiles").select("id, username, avatar_url").in_("id", ids).execute())
    return {row.get("id"): row for row in (unwrap(result) or [])}


async def count_rows_by_post(client: AsyncClient, table: str, post_ids: list[str]) -> dict[str, int]:
    if not post_ids:
        return {}
    result = await run_db(lambda: client.table(table).select("post_id").in_("post_id", post_ids).execute())
    counts: dict[str, int] = {}
    for row in unwrap(result) or []:
        post_id = row.get("post_id")
        counts[post_id] = counts.get(post_id, 0) + 1
    return counts


async def liked_post_ids(client: AsyncClient, user_id: str, post_ids: list[str]) -> set[str]:
    if not user_id or not post_ids:
        return set()
    rows = await _select_filtered(client, "post_likes", [("user_id", user_id)])
    allowed = set(post_ids)
    return {row["post_id"] for row in rows if row.get("post_id") in allowed}


async def get_post(client: AsyncClient, post_id: str) -> dict[str, Any] | None:
    rows = await _select_filtered(client, "posts", [("id", post_id)])
    return rows[0] if rows else None


async def get_comment(client: AsyncClient, comment_id: str) -> dict[str, Any] | None:
    rows = await _select_filtered(client, "post_comments", [("id", comment_id)])
    return rows[0] if rows else None


async def create_post(client: AsyncClient, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = {
        "user_id": user_id,
        "title": payload.get("title"),
        "content": payload["content"],
        "cover_image_url": payload.get("coverImageUrl"),
        "status": "published",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await run_db(lambda: client.table("posts").insert(row).select("*").single().execute())
    return unwrap(result) or row


async def update_post(client: AsyncClient, post_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    result = await run_db(lambda: client.table("posts").update(payload).eq("id", post_id).select("*").single().execute())
    return unwrap(result)


async def delete_by_id(client: AsyncClient, table: str, column: str, value: str) -> None:
    await run_db(lambda: client.table(table).delete().eq(column, value).execute())


async def create_comment(client: AsyncClient, user_id: str, post_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = {
        "post_id": post_id,
        "user_id": user_id,
        "content": payload["content"],
        "parent_comment_id": payload.get("parentCommentId"),
        "status": "published",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await run_db(lambda: client.table("post_comments").insert(row).select("*").single().execute())
    return unwrap(result) or row


async def update_comment(client: AsyncClient, comment_id: str, content: str) -> dict[str, Any] | None:
    result = await run_db(
        lambda: client.table("post_comments")
        .update({"content": content, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", comment_id)
        .select("*")
        .single()
        .execute()
    )
    return unwrap(result)


async def post_exists(client: AsyncClient, post_id: str) -> bool:
    return await get_post(client, post_id) is not None


async def toggle_like(client: AsyncClient, user_id: str, post_id: str, liked: bool) -> bool:
    """Set the caller's like state for a post; both directions are idempotent.

    Liking twice must not raise: the `(post_id, user_id)` composite key makes
    the second insert a duplicate, which we treat as already-liked.
    """
    if liked:
        await run_db(
            lambda: client.table("post_likes")
            .delete()
            .eq("post_id", post_id)
            .eq("user_id", user_id)
            .execute()
        )
        return False
    existing = await _select_filtered(
        client, "post_likes", [("post_id", post_id), ("user_id", user_id)]
    )
    if existing:
        return True
    try:
        await run_db(
            lambda: client.table("post_likes")
            .insert(
                {
                    "post_id": post_id,
                    "user_id": user_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .execute()
        )
    except Exception as exc:
        # 23505 = unique violation: a concurrent request already liked it.
        if getattr(exc, "code", None) != "23505":
            raise
    return True


async def like_count(client: AsyncClient, post_id: str) -> int:
    rows = await _select_filtered(client, "post_likes", [("post_id", post_id)])
    return len(rows)
