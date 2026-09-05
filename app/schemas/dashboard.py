"""Dashboard transport models (FR-007: shapes mirror dashboardService.ts)."""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class TaskStatus(str, Enum):
    pending = "pending"
    completed = "completed"


class VoucherStatus(str, Enum):
    locked = "locked"
    unlocked = "unlocked"


class DashboardTask(BaseModel):
    taskId: str
    name: str
    isMandatory: bool
    status: TaskStatus


class DashboardVoucher(BaseModel):
    voucherId: str
    title: str
    discountValue: str
    status: str
    requiredTaskId: str | None = None


class DashboardData(BaseModel):
    tasks: list[DashboardTask]
    vouchers: list[DashboardVoucher]


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


class VoucherStatusUpdate(BaseModel):
    status: VoucherStatus
