"""Authenticated Business Intelligence workspace routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.deps.auth import AuthenticatedUser, require_business_user
from app.deps.db import get_supabase
from app.errors import NotFoundError
from app.schemas.business_intelligence import (
    ActionPreviewRequest,
    ActionPreviewResponse,
    AgentRunRequest,
    AgentRunResponse,
    BIChatRequest,
    BIChatResponse,
    BIOverviewResponse,
    ReportCreateRequest,
    ReportCreateResponse,
)
from business_intelligence import service

router = APIRouter(prefix="/business-intelligence", tags=["business-intelligence"])


@router.get("/overview", response_model=BIOverviewResponse)
async def get_overview(
    user: Annotated[AuthenticatedUser, Depends(require_business_user)],
    client: Any = Depends(get_supabase),
) -> BIOverviewResponse:
    data = await service.overview(client, user_id=user.user_id, role=user.role or "")
    return BIOverviewResponse(**data)


@router.post("/agents/run", response_model=AgentRunResponse)
async def run_agent(
    body: AgentRunRequest,
    user: Annotated[AuthenticatedUser, Depends(require_business_user)],
    client: Any = Depends(get_supabase),
) -> AgentRunResponse:
    try:
        agent, activity = await service.run_agent(
            client, body.agentId, user_id=user.user_id, role=user.role or ""
        )
    except KeyError as exc:
        raise NotFoundError("Agent not found.") from exc
    return AgentRunResponse(agent=agent, activity=activity)


@router.post("/reports", response_model=ReportCreateResponse)
async def create_report(
    body: ReportCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(require_business_user)],
    client: Any = Depends(get_supabase),
) -> ReportCreateResponse:
    report, activity = await service.create_report(
        client, body.period, user_id=user.user_id, role=user.role or ""
    )
    return ReportCreateResponse(report=report, activity=activity)


@router.post("/actions/preview", response_model=ActionPreviewResponse)
async def preview_action(
    body: ActionPreviewRequest,
    user: Annotated[AuthenticatedUser, Depends(require_business_user)],
    client: Any = Depends(get_supabase),
) -> ActionPreviewResponse:
    recommendation = await service.get_recommendation(
        client, body.recommendationId, user_id=user.user_id, role=user.role or ""
    )
    if recommendation is None:
        raise NotFoundError("Recommendation not found.")
    return ActionPreviewResponse(
        recommendation=recommendation,
        status="preview",
        message=(
            "This is a simulated action preview. "
            "No business data or campaign has been changed."
        ),
    )


@router.post("/chat", response_model=BIChatResponse)
async def chat(
    body: BIChatRequest,
    user: Annotated[AuthenticatedUser, Depends(require_business_user)],
    client: Any = Depends(get_supabase),
) -> BIChatResponse:
    data = await service.overview(client, user_id=user.user_id, role=user.role or "")
    result = service.chat_reply(body.message, data)
    return BIChatResponse(
        reply=result["reply"],
        activityIds=result.get("activityIds") or [],
        recommendationIds=result.get("recommendationIds") or [],
    )
