"""Business API with exact-role and resource-ownership authorization."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.auth.models import CurrentUser
from app.auth.permissions import require_vendor
from app.deps.db import get_supabase, run_db, unwrap
from app.errors import ForbiddenError, NotFoundError
from app.schemas.admin import ServiceStatusUpdate

router = APIRouter(prefix="/business", tags=["business"], dependencies=[Depends(require_vendor)])
VendorUser = Annotated[CurrentUser, Depends(require_vendor)]


async def _owned_vendor_ids(client, user_id: str) -> list[str]:
    result = await run_db(
        lambda: client.table("vendors").select("id").eq("owner_id", user_id).execute()
    )
    return [str(row["id"]) for row in (unwrap(result) or []) if row.get("id")]


async def _owned_rows(client, table: str, user_id: str) -> list[dict]:
    vendor_ids = await _owned_vendor_ids(client, user_id)
    if not vendor_ids:
        return []
    result = await run_db(
        lambda: client.table(table).select("*").in_("vendor_id", vendor_ids).order("created_at", desc=True).execute()
    )
    return unwrap(result) or []


async def require_service_owner(client, service_id: str, user_id: str) -> dict:
    result = await run_db(
        lambda: client.table("services").select("*").eq("id", service_id).execute()
    )
    rows = unwrap(result) or []
    if not rows:
        raise NotFoundError()
    service = rows[0]
    if service.get("vendor_id") not in await _owned_vendor_ids(client, user_id):
        raise ForbiddenError("You do not have permission to modify this resource.")
    return service


@router.get("/services")
async def services(user: VendorUser, client=Depends(get_supabase)) -> list[dict]:
    return await _owned_rows(client, "services", user.id)


@router.put("/services/{serviceId}/status")
async def update_service_status(
    service_id: Annotated[str, Path(alias="serviceId", min_length=1)],
    body: ServiceStatusUpdate,
    user: VendorUser,
    client=Depends(get_supabase),
) -> dict[str, bool]:
    await require_service_owner(client, service_id, user.id)
    await run_db(
        lambda: client.table("services")
        .update({"status": body.status.value})
        .eq("id", service_id)
        .execute()
    )
    return {"ok": True}


@router.get("/service-requests")
async def service_requests(user: VendorUser, client=Depends(get_supabase)) -> list[dict]:
    return await _owned_rows(client, "service_requests", user.id)


@router.get("/vouchers")
async def vouchers(user: VendorUser, client=Depends(get_supabase)) -> list[dict]:
    return await _owned_rows(client, "vouchers", user.id)
