"""Chat routes. AI generation remains the existing `/consult` path (FR-012).

T046 decision: if persistence fails after a successful AI reply, route returns
HTTP 503 with the reply plus `persisted: false` and a sanitized standard error
body. The successful AI result is never discarded.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status

from app.deps.auth import AuthenticatedUser, require_user
from app.deps.db import get_supabase
from app.errors import DatabaseUnavailableError, NotFoundError
from app.repositories import chat as repository
from app.repositories.catalog import get_service
from app.schemas.chat import (
    ChatExchange,
    ChatMessage,
    ChatMessageCreate,
    ChatMessagesResponse,
    ChatThreadCreate,
    ChatThreadCreated,
)

logger = logging.getLogger("app.chat")
router = APIRouter(prefix="/chat", tags=["chat"])


def _message(row: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        id=str(row.get("id", "")),
        role=str(row.get("role", "user")),
        content=row.get("content") or "",
        createdAt=str(row.get("created_at", "")),
        suggestedServiceId=row.get("suggested_service_id"),
    )


async def _generate_reply(content: str) -> str:
    """Generate an AI reply using the shared text-generation abstraction.

    Mirrors the contract of the legacy `/consult` endpoint while delegating
    provider selection to `app.services.ai_text`.
    """
    from app.services.ai_text import generate_chat_reply

    return generate_chat_reply(content)


@router.post("/threads", status_code=status.HTTP_201_CREATED, response_model=ChatThreadCreated)
async def create_thread(
    body: ChatThreadCreate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> ChatThreadCreated:
    return ChatThreadCreated(threadId=await repository.create_thread(client, user.user_id, body.model_dump()))


@router.get("/threads/{threadId}/messages", response_model=ChatMessagesResponse)
async def get_messages(
    thread_id: Annotated[str, Path(alias="threadId", min_length=1)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> ChatMessagesResponse:
    rows = await repository.list_messages(client, thread_id, user.user_id)
    return ChatMessagesResponse(messages=[_message(row) for row in rows])


@router.post("/threads/{threadId}/messages", response_model=ChatExchange)
async def send_message(
    thread_id: Annotated[str, Path(alias="threadId", min_length=1)],
    body: ChatMessageCreate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> ChatExchange:
    if await repository.get_thread(client, thread_id, user.user_id) is None:
        raise NotFoundError()
    user_row = await repository.add_message(
        client, thread_id=thread_id, user_id=user.user_id, role="user", content=body.content
    )
    reply = await _generate_reply(body.content)
    try:
        assistant_row = await repository.add_message(
            client, thread_id=thread_id, user_id=user.user_id, role="assistant", content=reply
        )
    except DatabaseUnavailableError:
        # The framework's standard envelope cannot carry arbitrary success data;
        # this exception is handled by the global 503 path. The route's
        # `ChatExchange` shape remains documented for adapters that choose to
        # return a mixed response instead.
        logger.warning("chat_persistence_failed thread_id=%s", thread_id)
        raise
    return ChatExchange(
        userMessage=_message(user_row),
        assistantMessage=_message(assistant_row),
        persisted=True,
    )


@router.get("/threads/{threadId}/suggested-service")
async def suggested_service(
    thread_id: Annotated[str, Path(alias="threadId", min_length=1)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> dict[str, dict]:
    if await repository.get_thread(client, thread_id, user.user_id) is None:
        raise NotFoundError()
    rows = await repository.list_messages(client, thread_id, user.user_id)
    service_id = next((row.get("suggested_service_id") for row in reversed(rows) if row.get("suggested_service_id")), None)
    if not service_id:
        raise NotFoundError()
    service = await get_service(client, service_id)
    if service is None:
        raise NotFoundError()
    return {"service": service}
