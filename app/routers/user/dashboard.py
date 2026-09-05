"""Customer dashboard routes under ``/api/v1/me``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.auth.models import CurrentUser
from app.auth.permissions import require_customer
from app.deps.db import get_supabase
from app.repositories import dashboard as repository
from app.schemas.dashboard import DashboardData, TaskStatusUpdate, VoucherStatusUpdate
from app.services import dashboard as service

router = APIRouter(
    prefix="/me",
    tags=["dashboard"],
)


@router.get("/dashboard", response_model=DashboardData)
async def get_dashboard(
    user: Annotated[CurrentUser, Depends(require_customer)],
    client=Depends(get_supabase),
) -> DashboardData:
    journey_tasks = await repository.list_journey_tasks(client)
    user_tasks = await repository.list_user_journey_tasks(client, user.id)
    vouchers = await repository.list_vouchers(client)
    user_vouchers = await repository.list_user_vouchers(client, user.id)

    return DashboardData(
        tasks=service.map_dashboard_tasks(journey_tasks, user_tasks),
        vouchers=service.map_dashboard_vouchers(vouchers, user_vouchers),
    )


@router.put("/journey-tasks/{taskId}")
async def update_journey_task(
    task_id: Annotated[str, Path(alias="taskId", min_length=1)],
    body: TaskStatusUpdate,
    user: Annotated[CurrentUser, Depends(require_customer)],
    client=Depends(get_supabase),
) -> dict[str, bool]:
    completed_at, updated_at = service.task_timestamps(body.status)
    await repository.upsert_user_journey_task(
        client,
        user_id=user.id,
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
    user: Annotated[CurrentUser, Depends(require_customer)],
    client=Depends(get_supabase),
) -> dict[str, bool]:
    await repository.upsert_user_voucher(
        client,
        user_id=user.id,
        voucher_id=voucher_id,
        status=body.status.value,
        unlocked_at=service.voucher_unlocked_at(body.status.value),
    )
    return {"ok": True}
