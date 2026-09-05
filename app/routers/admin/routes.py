"""Admin routes — every endpoint gated by `require_admin` (FR-005, SC-003).

Authorization is enforced once at the router level through the centralized
JWT, profile-role, and exact-admin dependency chain.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.auth.permissions import require_admin
from app.deps.db import get_supabase_admin
from app.errors import NotFoundError
from app.repositories import admin as repository
from app.repositories import analytics as analytics_repository
from app.schemas.admin import (
    ApplicationRoleUpdate,
    CommentStatusUpdate,
    JourneyTaskUpdate,
    JourneyTaskWrite,
    PlatformMetrics,
    PostStatusUpdate,
    ProfileNameRequest,
    RoleUpdate,
    ServiceRequestStatusUpdate,
    ServiceStatusUpdate,
    VendorStatusUpdate,
    VoucherPartialWrite,
    VoucherWrite,
    WebsiteAnalytics,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/metrics", response_model=PlatformMetrics)
async def metrics(client=Depends(get_supabase_admin)) -> PlatformMetrics:
    return PlatformMetrics(**await repository.fetch_platform_metrics(client))


@router.get("/profiles")
async def profiles(
    search: Annotated[str | None, Query()] = None,
    client=Depends(get_supabase_admin),
) -> list[dict]:
    return await repository.list_profiles(client, search)


@router.put("/profiles/{id}/role")
async def set_profile_role(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: RoleUpdate,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    if await repository.get_row(client, "profiles", row_id) is None:
        raise NotFoundError()
    await repository.update_row(
        client, "profiles", row_id, {"role": body.role.value}
    )
    return {"ok": True}


@router.put("/users/{id}/role")
async def set_application_role(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: ApplicationRoleUpdate,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    """Privileged, validated transition of the authoritative application role."""
    if await repository.get_row(client, "profiles", row_id) is None:
        raise NotFoundError()
    await repository.update_row(
        client, "profiles", row_id, {"role": body.role.value}
    )
    return {"ok": True}


async def _delete(client, table: str, row_id: str) -> dict[str, bool]:
    if await repository.get_row(client, table, row_id) is None:
        raise NotFoundError()
    await repository.delete_row(client, table, row_id)
    return {"ok": True}


@router.delete("/profiles/{id}")
async def delete_profile(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    return await _delete(client, "profiles", row_id)


@router.get("/vendors")
async def vendors(client=Depends(get_supabase_admin)) -> list[dict]:
    return await repository._list(client, "vendors", order="created_at")


@router.put("/vendors/{id}/status")
async def set_vendor_status(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: VendorStatusUpdate,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    if await repository.get_row(client, "vendors", row_id) is None:
        raise NotFoundError()
    await repository.update_row(client, "vendors", row_id, {"status": body.status.value})
    return {"ok": True}


@router.delete("/vendors/{id}")
async def delete_vendor(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    return await _delete(client, "vendors", row_id)


@router.get("/services")
async def services(client=Depends(get_supabase_admin)) -> list[dict]:
    return await repository._list(client, "services", order="created_at")


@router.put("/services/{id}/status")
async def set_service_status(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: ServiceStatusUpdate,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    if await repository.get_row(client, "services", row_id) is None:
        raise NotFoundError()
    await repository.update_row(client, "services", row_id, {"status": body.status.value})
    return {"ok": True}


@router.delete("/services/{id}")
async def delete_service(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    return await _delete(client, "services", row_id)


@router.get("/posts")
async def posts(client=Depends(get_supabase_admin)) -> list[dict]:
    return await repository._list(client, "posts", order="created_at")


@router.put("/posts/{id}/status")
async def set_post_status(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: PostStatusUpdate,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    if await repository.get_row(client, "posts", row_id) is None:
        raise NotFoundError()
    await repository.update_row(client, "posts", row_id, {"status": body.status.value})
    return {"ok": True}


@router.delete("/posts/{id}")
async def delete_post(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    return await _delete(client, "posts", row_id)


@router.get("/comments")
async def comments(client=Depends(get_supabase_admin)) -> list[dict]:
    return await repository._list(client, "post_comments", order="created_at")


@router.put("/comments/{id}/status")
async def set_comment_status(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: CommentStatusUpdate,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    if await repository.get_row(client, "post_comments", row_id) is None:
        raise NotFoundError()
    await repository.update_row(client, "post_comments", row_id, {"status": body.status.value})
    return {"ok": True}


@router.delete("/comments/{id}")
async def delete_comment(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    return await _delete(client, "post_comments", row_id)


@router.get("/journey-tasks")
async def journey_tasks(client=Depends(get_supabase_admin)) -> list[dict]:
    return await repository._list(client, "journey_tasks", order="display_order", desc=False)


@router.post("/journey-tasks")
async def create_journey_task(
    body: JourneyTaskWrite, client=Depends(get_supabase_admin)
) -> dict:
    return await repository.insert_row(client, "journey_tasks", body.model_dump())


@router.put("/journey-tasks/{id}")
async def update_journey_task(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: JourneyTaskUpdate,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    if await repository.get_row(client, "journey_tasks", row_id) is None:
        raise NotFoundError()
    await repository.update_row(client, "journey_tasks", row_id, body.model_dump(exclude_none=True))
    return {"ok": True}


@router.delete("/journey-tasks/{id}")
async def delete_journey_task(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    return await _delete(client, "journey_tasks", row_id)


@router.get("/vouchers")
async def vouchers(client=Depends(get_supabase_admin)) -> list[dict]:
    return await repository._list(client, "vouchers", order="created_at")


@router.post("/vouchers")
async def create_voucher(
    body: VoucherWrite, client=Depends(get_supabase_admin)
) -> dict:
    payload = body.model_dump()
    payload["discount_type"] = body.discount_type.value
    return await repository.insert_row(client, "vouchers", payload)


@router.put("/vouchers/{id}")
async def update_voucher(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: VoucherPartialWrite,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    if await repository.get_row(client, "vouchers", row_id) is None:
        raise NotFoundError()
    payload = body.model_dump(exclude_none=True)
    if body.discount_type is not None:
        payload["discount_type"] = body.discount_type.value
    await repository.update_row(client, "vouchers", row_id, payload)
    return {"ok": True}


@router.delete("/vouchers/{id}")
async def delete_voucher(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    return await _delete(client, "vouchers", row_id)


@router.get("/service-requests")
async def service_requests(client=Depends(get_supabase_admin)) -> list[dict]:
    return await repository._list(client, "service_requests", order="created_at")


@router.put("/service-requests/{id}/status")
async def set_service_request_status(
    row_id: Annotated[str, Path(alias="id", min_length=1)],
    body: ServiceRequestStatusUpdate,
    client=Depends(get_supabase_admin),
) -> dict[str, bool]:
    if await repository.get_row(client, "service_requests", row_id) is None:
        raise NotFoundError()
    await repository.update_row(client, "service_requests", row_id, {"status": body.status.value})
    return {"ok": True}


@router.post("/profile-names", response_model=dict[str, str])
async def profile_names(
    body: ProfileNameRequest,
    client=Depends(get_supabase_admin),
) -> dict[str, str]:
    """Resolve display names for a set of user IDs (batch)."""
    return await repository.profile_names(client, body.user_ids)


@router.get("/analytics", response_model=WebsiteAnalytics)
async def analytics(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    client=Depends(get_supabase_admin),
) -> WebsiteAnalytics:
    payload = await analytics_repository.get_admin_website_analytics(client, days)
    summary = payload.get("summary") or {}
    return WebsiteAnalytics(
        summary={
            "views": int(summary.get("views") or 0),
            "uniqueVisitors": int(summary.get("uniqueVisitors") or 0),
            "sessions": int(summary.get("sessions") or 0),
            "avgDurationSeconds": int(summary.get("avgDurationSeconds") or 0),
            "bounceRate": float(summary.get("bounceRate") or 0),
        },
        pages=payload.get("pages") or [],
        behaviours=payload.get("behaviours") or [],
        daily=payload.get("daily") or [],
    )
