"""Health check router.

Exposes a public ``/health`` endpoint that reports liveness and readiness
information without requiring any upstream dependency to be reachable
(Constitution Principle V, III).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["health"])
logger = logging.getLogger("app.health")


class HealthResponse(BaseModel):
    ok: bool
    service: str
    model: str
    provider: str
    project: str
    location: str
    vertex_configured: bool


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
async def health() -> HealthResponse:
    """Return service health.  Never gated by auth (Constitution III)."""
    settings = get_settings()
    return HealthResponse(
        ok=True,
        service="LOMAR Business Intelligence API",
        model=settings.ai_text_model or settings.google_text_model,
        provider="vertex-ai" if settings.vertex_configured else "genai",
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        vertex_configured=settings.vertex_configured,
    )
