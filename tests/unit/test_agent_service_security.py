from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.agent_service import execute_consultant


@pytest.mark.asyncio
async def test_backend_uses_internal_credential_and_trusted_user_context(settings_override):
    settings_override(
        agent_service_url="https://agent.internal",
        agent_service_internal_key="internal-secret",
    )
    response = httpx.Response(
        200,
        json={"output": {"reply": "ok", "sessionId": "s1"}},
        request=httpx.Request("POST", "https://agent.internal"),
    )
    post = AsyncMock(return_value=response)

    with patch("app.services.agent_service.httpx.AsyncClient") as client_type:
        client_type.return_value.__aenter__.return_value.post = post
        result = await execute_consultant(
            user_id="verified-user",
            message="hello",
            session_id=None,
            history=[],
        )

    assert result["reply"] == "ok"
    _, kwargs = post.call_args
    assert kwargs["headers"] == {"X-Internal-Service-Key": "internal-secret"}
    assert kwargs["json"]["user_id"] == "verified-user"
    assert "role" not in kwargs["json"]
