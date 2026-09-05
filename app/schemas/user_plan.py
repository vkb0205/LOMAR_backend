"""User wedding-plan acceptance transport models (feature 003).

The Accept/Decline/Remove endpoint is always authenticated
(``/api/v1/me/*``), so ``user_id`` is never carried in the body — it is forced
from the verified JWT by the centralized customer dependency (data-model.md
invariant 1).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class PlanItemType(str, Enum):
    """Which catalog entity a plan item references."""

    service = "service"
    plan = "plan"


class PlanItemStatus(str, Enum):
    """Mutable decision state of a plan item (FR-003)."""

    accepted = "accepted"
    declined = "declined"
    removed = "removed"


class PlanItemAction(BaseModel):
    """Body of an Accept/Decline/Remove request.

    The status is restricted to the user-decision set — ``proposed`` is a
    system-only state and cannot be set by a caller.
    """

    status: PlanItemStatus


class AcceptedPlanItem(BaseModel):
    """One row of the accepted-plan view (owner-scoped, allowlisted)."""

    userId: str
    itemType: Literal["service", "plan"]
    category: str | None = None
    serviceId: str | None = None
    serviceName: str | None = None
    servicePrice: float | None = None
    planId: str | None = None
    planName: str | None = None
    acceptedAt: str | None = None


class PlanItemUpdated(BaseModel):
    """Success response of Accept/Decline/Remove."""

    itemType: PlanItemType
    itemId: str
    status: PlanItemStatus
    ok: bool = True
