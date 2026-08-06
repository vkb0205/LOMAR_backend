"""Dashboard HTTP routes — `/api/v1/me/*`, always authenticated (T008)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.deps.auth import AuthenticatedUser, require_user
from app.deps.db import get_supabase
from app.repositories import dashboard as repository
from app.schemas.dashboard import DashboardData, TaskStatusUpdate, VoucherStatusUpdate
from app.services import dashboard as service

router = APIRouter(prefix="/me", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardData)
async def get_dashboard(
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> DashboardData:
    journey_tasks = await repository.list_journey_tasks(client)
    user_tasks = await repository.list_user_journey_tasks(client, user.user_id)
    vouchers = await repository.list_vouchers(client)
    user_vouchers = await repository.list_user_vouchers(client, user.user_id)
    saved_designs = await repository.list_saved_designs(client, user.user_id)

    return DashboardData(
        tasks=service.map_dashboard_tasks(journey_tasks, user_tasks),
        vouchers=service.map_dashboard_vouchers(vouchers, user_vouchers),
        savedDesigns=saved_designs,
    )


@router.put("/journey-tasks/{taskId}")
async def update_journey_task(
    task_id: Annotated[str, Path(alias="taskId", min_length=1)],
    body: TaskStatusUpdate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> dict[str, bool]:
    completed_at, updated_at = service.task_timestamps(body.status)
    await repository.upsert_user_journey_task(
        client,
        user_id=user.user_id,
        task_id=task_id,
        status=body.status.value,
        completed_at=completed_at,
        updated_at=updated_at,
    )
    return {"ok": True}


@router.put("/vouchers/{voucherId}")
async def update_voucher(
    voucher_id: Annotated[str, Path(alias="voucherId", min_length=1)],
    body: VoucherStatusUpdate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> dict[str, bool]:
    await repository.upsert_user_voucher(
        client,
        user_id=user.user_id,
        voucher_id=voucher_id,
        status=body.status.value,
        unlocked_at=service.voucher_unlocked_at(body.status.value),
    )
    return {"ok": True}
