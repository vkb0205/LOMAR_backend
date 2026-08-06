"""Dashboard domain logic.

The join + status normalization here is a direct port of the mappers that
used to live in `LOMAR/src/features/dashboard/services/dashboardService.ts`
(`normalizeTaskStatus`, `mapDashboardTasks`, `mapDashboardVouchers`), so the
frontend receives byte-identical view models (FR-007, T030).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.dashboard import DashboardTask, DashboardVoucher, TaskStatus


def now_iso() -> str:
    """UTC timestamp in the ISO-8601 form the frontend previously produced."""
    return datetime.now(timezone.utc).isoformat()


def normalize_task_status(status: str | None) -> TaskStatus:
    """`completed` (case-insensitive) is completed; everything else pending."""
    if status is not None and status.lower() == "completed":
        return TaskStatus.completed
    return TaskStatus.pending


def map_dashboard_tasks(
    journey_tasks: list[dict[str, Any]],
    user_tasks: list[dict[str, Any]],
) -> list[DashboardTask]:
    progress_by_task = {row.get("task_id"): row for row in user_tasks}
    tasks: list[DashboardTask] = []
    for task in journey_tasks:
        progress = progress_by_task.get(task.get("id"))
        tasks.append(
            DashboardTask(
                taskId=str(task.get("id", "")),
                name=task.get("name") or "Nhiệm vụ",
                isMandatory=bool(task.get("is_mandatory") or False),
                status=normalize_task_status(progress.get("status") if progress else None),
            )
        )
    return tasks


def map_dashboard_vouchers(
    vouchers: list[dict[str, Any]],
    user_vouchers: list[dict[str, Any]],
) -> list[DashboardVoucher]:
    claim_by_voucher = {row.get("voucher_id"): row for row in user_vouchers}
    mapped: list[DashboardVoucher] = []
    for voucher in vouchers:
        claim = claim_by_voucher.get(voucher.get("id"))
        raw_status = claim.get("status") if claim else None
        discount_value = voucher.get("discount_value")
        mapped.append(
            DashboardVoucher(
                voucherId=str(voucher.get("id", "")),
                title=voucher.get("title") or "Voucher",
                discountValue="" if discount_value is None else str(discount_value),
                status=(raw_status.lower() if isinstance(raw_status, str) else "locked"),
                requiredTaskId=voucher.get("required_task_id") or None,
            )
        )
    return mapped


def task_timestamps(status: TaskStatus) -> tuple[str | None, str]:
    """Server-owned timestamps (data-model.md invariant 7).

    Completion sets `completed_at`; reversing to pending clears it.
    """
    stamp = now_iso()
    return (stamp if status is TaskStatus.completed else None), stamp


def voucher_unlocked_at(status: str) -> str | None:
    """`unlocked_at` is set on unlock and cleared on re-lock (invariant 7)."""
    return now_iso() if status == "unlocked" else None
