"""User wedding-plan acceptance routes — `/api/v1/me/plan-items/*`.

Always authenticated via the centralized customer-role boundary (FR-007):
anonymous callers get 401 and non-customer roles get 403.
The item id is routed to either ``services`` or ``wedding_plans`` by
``itemType`` and validated to exist as ``active`` before any write (unknown
items → 404; invalid status → 422 by schema validation).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path

from app.auth.models import CurrentUser
from app.auth.permissions import require_customer
from app.deps.db import get_supabase
from app.repositories import user_plan as repository
from app.schemas.user_plan import PlanItemAction, PlanItemUpdated, PlanItemType
from app.services import user_plan as service

router = APIRouter(prefix="/me", tags=["user-plan"])


@router.put("/plan-items/{itemType}/{itemId}", response_model=PlanItemUpdated)
async def update_plan_item(
    item_type: Annotated[Literal["service", "plan"], Path(alias="itemType")],
    item_id: Annotated[str, Path(alias="itemId", min_length=1)],
    body: PlanItemAction,
    user: Annotated[CurrentUser, Depends(require_customer)],
    client=Depends(get_supabase),
) -> PlanItemUpdated:
    """Accept, decline or remove one catalog item on the caller's plan."""
    accepted_at, updated_at = service.accepted_timestamps(body.status)
    await repository.upsert_plan_item(
        client,
        user_id=user.id,
        item_type=item_type,
        item_id=item_id,
        status=body.status.value,
        accepted_at=accepted_at,
        updated_at=updated_at,
    )
    return PlanItemUpdated(
        itemType=PlanItemType(item_type),
        itemId=item_id,
        status=body.status,
    )
