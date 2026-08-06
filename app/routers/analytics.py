"""Public analytics tracking routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.deps.auth import AuthenticatedUser, current_user
from app.deps.db import get_supabase
from app.repositories import analytics as repository
from app.schemas.admin import PageEngagementCreate, PageViewCreate

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/page-views")
async def record_view(
    body: PageViewCreate,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    client=Depends(get_supabase),
) -> dict[str, bool]:
    # RPC signature stays unchanged; user identity comes from auth.uid() inside
    # the security-definer function. Do not pass arbitrary client user_id.
    await repository.record_page_view(
        client,
        {
            "p_id": body.id,
            "p_session_id": body.sessionId,
            "p_visitor_id": body.visitorId,
            "p_page_path": body.pagePath,
            "p_page_title": body.pageTitle,
            "p_referrer_host": body.referrerHost,
        },
    )
    return {"ok": True}


@router.post("/page-views/{viewId}/engagement")
async def record_engagement(
    view_id: Annotated[str, Path(alias="viewId", min_length=1)],
    body: PageEngagementCreate,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    client=Depends(get_supabase),
) -> dict[str, bool]:
    await repository.record_page_engagement(
        client,
        {
            "p_id": view_id,
            "p_session_id": body.sessionId,
            "p_visitor_id": body.visitorId,
            "p_duration_seconds": body.durationSeconds,
            "p_max_scroll_percent": body.maxScrollPercent,
        },
    )
    return {"ok": True}
