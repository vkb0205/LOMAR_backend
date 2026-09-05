"""Authenticated Backend -> Agent Service transport."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.errors import UpstreamUnavailableError


async def execute_consultant(
    *, user_id: str, message: str, session_id: str | None, history: list[dict[str, str]]
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.agent_service_url or not settings.agent_service_internal_key:
        raise UpstreamUnavailableError("The AI consultant is not configured.")
    body = {
        "user_id": user_id,
        "session_id": session_id,
        "input": {"message": message, "history": history},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.agent_service_timeout_seconds) as client:
            response = await client.post(
                f"{settings.agent_service_url.rstrip('/')}/api/v1/agents/consultant/execute",
                headers={"X-Internal-Service-Key": settings.agent_service_internal_key},
                json=body,
            )
            response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise UpstreamUnavailableError("The AI consultant is temporarily unavailable.") from exc
    payload = response.json()
    output = payload.get("output")
    if not isinstance(output, dict):
        raise UpstreamUnavailableError("The AI consultant returned an invalid response.")
    return output
