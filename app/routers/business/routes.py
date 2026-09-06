"""Vendor-tier API with resource-ownership authorization."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.auth.models import CurrentUser
from app.auth.permissions import require_vendor
from app.deps.db import get_supabase, run_db, unwrap
from app.errors import ForbiddenError, NotFoundError
from app.schemas.admin import ServiceStatusUpdate
from app.services.authz import LOMAR_ROLE_ADMIN
from .business_intelligence import router as business_intelligence_router

router = APIRouter()
operations_router = APIRouter(
    prefix="/business",
    tags=["business"],
    dependencies=[Depends(require_vendor)],
)
VendorUser = Annotated[CurrentUser, Depends(require_vendor)]


async def _owned_vendor_ids(client, user_id: str) -> list[str]:
    result = await run_db(
        lambda: client.table("vendors").select("id").eq("owner_id", user_id).execute()
    )
    return [str(row["id"]) for row in (unwrap(result) or []) if row.get("id")]


async def _accessible_rows(client, table: str, user: CurrentUser) -> list[dict]:
    if user.role == LOMAR_ROLE_ADMIN:
        result = await run_db(
            lambda: client.table(table).select("*").order("created_at", desc=True).execute()
        )
        return unwrap(result) or []

    vendor_ids = await _owned_vendor_ids(client, user.id)
    if not vendor_ids:
        return []
    result = await run_db(
        lambda: client.table(table).select("*").in_("vendor_id", vendor_ids).order("created_at", desc=True).execute()
    )
    return unwrap(result) or []


async def require_service_access(client, service_id: str, user: CurrentUser) -> dict:
    result = await run_db(
        lambda: client.table("services").select("*").eq("id", service_id).execute()
    )
    rows = unwrap(result) or []
    if not rows:
        raise NotFoundError()
    service = rows[0]
    if (
        user.role != LOMAR_ROLE_ADMIN
        and service.get("vendor_id") not in await _owned_vendor_ids(client, user.id)
    ):
        raise ForbiddenError("You do not have permission to modify this resource.")
    return service


@operations_router.get("/services")
async def services(user: VendorUser, client=Depends(get_supabase)) -> list[dict]:
    return await _accessible_rows(client, "services", user)


@operations_router.put("/services/{serviceId}/status")
async def update_service_status(
    service_id: Annotated[str, Path(alias="serviceId", min_length=1)],
    body: ServiceStatusUpdate,
    user: VendorUser,
    client=Depends(get_supabase),
) -> dict[str, bool]:
    await require_service_access(client, service_id, user)
    await run_db(
        lambda: client.table("services")
        .update({"status": body.status.value})
        .eq("id", service_id)
        .execute()
    )
    return {"ok": True}


@operations_router.get("/service-requests")
async def service_requests(user: VendorUser, client=Depends(get_supabase)) -> list[dict]:
    return await _accessible_rows(client, "service_requests", user)


@operations_router.get("/vouchers")
async def vouchers(user: VendorUser, client=Depends(get_supabase)) -> list[dict]:
    return await _accessible_rows(client, "vouchers", user)


router.include_router(operations_router)
router.include_router(business_intelligence_router)
