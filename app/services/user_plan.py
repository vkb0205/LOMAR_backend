"""User wedding-plan domain logic (feature 003).

Server-owned timestamps only (data-model.md invariant 7): ``accepted_at`` is
stamped when a decision becomes ``accepted`` and cleared on any other status,
so an ``accepted -> declined`` transition immediately drops the row from the
accepted view (spec Edge Cases).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.user_plan import PlanItemStatus


def now_iso() -> str:
    """UTC timestamp in the ISO-8601 form the rest of the API emits."""
    return datetime.now(timezone.utc).isoformat()


def accepted_timestamps(status: PlanItemStatus) -> tuple[str | None, str]:
    """Return ``(accepted_at, updated_at)`` for a user decision.

    ``accepted_at`` is set on acceptance and cleared otherwise; ``updated_at``
    always moves to now so the row records the transition.
    """
    stamp = now_iso()
    return (stamp if status is PlanItemStatus.accepted else None), stamp
