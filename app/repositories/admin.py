"""Admin repository — cross-user reads/writes.

Service-role justification (Constitution II, research.md R2): admin
moderation must see and mutate every user's rows (profiles, vendors, posts,
etc). The caller's own JWT is scoped by RLS to their own rows; there is no
way to satisfy "an admin can moderate anyone's content" under the caller's
JWT alone. `require_admin` (app/deps/auth.py) has already independently
verified the caller's `profiles.role == 'admin'` via the caller-JWT client
*before* any function here runs, so this module never becomes the sole
gate — it only performs the operations RLS alone cannot under the caller's
identity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import AsyncClient

from app.deps.db import run_db, unwrap

_COUNT_TABLES = (
    "profiles",
    "vendors",
    "services",
    "posts",
    "post_comments",
    "reviews",
    "service_requests",
    "ai_design_generations",
)


async def count_rows(client: AsyncClient, table: str, filter_: tuple[str, str] | None = None) -> int:
    def build():
        query = client.table(table).select("*", count="exact", head=True)
        if filter_:
            query = query.eq(filter_[0], filter_[1])
        return query.execute()

    result = await run_db(build)
    return result.count or 0


async def _list(client: AsyncClient, table: str, *, order: str | None = None, desc: bool = True, limit: int | None = None) -> list[dict[str, Any]]:
    def build():
        query = client.table(table).select("*")
        if order:
            query = query.order(order, desc=desc)
        if limit:
            query = query.limit(limit)
        return query.execute()

    result = await run_db(build)
    return unwrap(result) or []


async def list_profiles(client: AsyncClient, search: str | None = None) -> list[dict[str, Any]]:
    def build():
        query = client.table("profiles").select("*").order("created_at", desc=True)
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.or_(f"full_name.ilike.{term},username.ilike.{term},email.ilike.{term}")
        return query.execute()

    result = await run_db(build)
    return unwrap(result) or []


async def update_row(client: AsyncClient, table: str, row_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    payload = {**payload, "updated_at": datetime.now(timezone.utc).isoformat()}
    result = await run_db(lambda: client.table(table).update(payload).eq("id", row_id).select("*").single().execute())
    return unwrap(result)


async def delete_row(client: AsyncClient, table: str, row_id: str) -> None:
    await run_db(lambda: client.table(table).delete().eq("id", row_id).execute())


async def insert_row(client: AsyncClient, table: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = await run_db(lambda: client.table(table).insert(payload).select("*").single().execute())
    return unwrap(result) or payload


async def get_row(client: AsyncClient, table: str, row_id: str) -> dict[str, Any] | None:
    result = await run_db(lambda: client.table(table).select("*").eq("id", row_id).execute())
    rows = unwrap(result) or []
    return rows[0] if rows else None


async def fetch_platform_metrics(client: AsyncClient) -> dict[str, int]:
    users = await count_rows(client, "profiles")
    vendors = await count_rows(client, "vendors")
    vendors_pending = await count_rows(client, "vendors", ("status", "draft"))
    services = await count_rows(client, "services")
    posts = await count_rows(client, "posts")
    posts_hidden = await count_rows(client, "posts", ("status", "hidden"))
    comments_flagged = await count_rows(client, "post_comments", ("status", "flagged"))
    reviews_flagged = await count_rows(client, "reviews", ("status", "flagged"))
    leads = await count_rows(client, "service_requests")
    leads_new = await count_rows(client, "service_requests", ("status", "new"))
    generations = await count_rows(client, "ai_design_generations")
    generations_failed = await count_rows(client, "ai_design_generations", ("status", "failed"))
    return {
        "users": users,
        "vendors": vendors,
        "vendorsPending": vendors_pending,
        "services": services,
        "posts": posts,
        "postsHidden": posts_hidden,
        "commentsFlagged": comments_flagged,
        "reviewsFlagged": reviews_flagged,
        "leads": leads,
        "leadsNew": leads_new,
        "generations": generations,
        "generationsFailed": generations_failed,
    }


async def profile_names(client: AsyncClient, user_ids: list[str]) -> dict[str, str]:
    unique = list(dict.fromkeys(uid for uid in user_ids if uid))
    if not unique:
        return {}
    result = await run_db(
        lambda: client.table("profiles").select("id, full_name, username, email").in_("id", unique).execute()
    )
    names: dict[str, str] = {}
    for row in unwrap(result) or []:
        names[row["id"]] = row.get("full_name") or row.get("username") or row.get("email") or row["id"][:8]
    return names
