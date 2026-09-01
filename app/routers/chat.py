"""Persistent chat thread routes for authenticated application surfaces.

T046 decision: if persistence fails after a successful AI reply, route returns
HTTP 503 with the reply plus `persisted: false` and a sanitized standard error
body. The successful AI result is never discarded.

Anonymous couple consult lives at ``POST /chat/consult`` and uses the tool-using
consultant agent plus process-local session memory (not durable threads).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status

from app.deps.auth import AuthenticatedUser, current_user, require_user
from app.deps.db import get_supabase
from app.errors import DatabaseUnavailableError, NotFoundError
from app.repositories import chat as repository
from app.repositories.catalog import get_service
from app.repositories import user_plan as user_plan_repository
from app.schemas.chat import (
    ChatExchange,
    ChatMessage,
    ChatMessageCreate,
    ChatMessagesResponse,
    ChatThreadCreate,
    ChatThreadCreated,
    ConsultRequest,
    ConsultResponse,
    RetrievedServiceCard,
)

logger = logging.getLogger("app.chat")
router = APIRouter(prefix="/chat", tags=["chat"])

_CONSULT_EMPTY_FALLBACK = (
    "Mình xin lỗi, mình chưa tổng hợp được câu trả lời vừa rồi. "
    "Bạn thử hỏi lại rõ hơn hoặc mở mục Khám phá để xem danh mục nhé."
)

# Client path/surface hints accepted as *display* context only. Never treat as
# authoritative routing or authorization input.
_ALLOWED_PATH_PREFIXES = (
    "/",
    "/explore",
    "/guide",
    "/blog",
    "/dashboard",
    "/login",
    "/vendor",
    "/services",
)


def _message(row: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        id=str(row.get("id", "")),
        role=str(row.get("role", "user")),
        content=row.get("content") or "",
        createdAt=str(row.get("created_at", "")),
        suggestedServiceId=row.get("suggested_service_id"),
    )


def _service_card(row: dict[str, Any]) -> RetrievedServiceCard | None:
    identifier = row.get("id")
    if not isinstance(identifier, str) or not identifier:
        return None
    return RetrievedServiceCard(
        id=identifier,
        name=row.get("name"),
        category=row.get("category"),
        basePrice=row.get("base_price"),
        currency=row.get("currency"),
        thumbnailUrl=row.get("thumbnail_url"),
        vendorId=row.get("vendor_id"),
    )


def _build_extra_context(
    *,
    path: str | None,
    surface: str | None,
    plan_summary: list[dict[str, Any]] | None = None,
) -> str | None:
    """Build trusted-shaped extra context from optional client display hints.

    ``plan_summary`` is server-derived and non-PII (categories + counts from the
    caller's accepted plan only); it is injected only when a valid JWT was
    present, never for anonymous consult (FR-008).
    """
    parts: list[str] = []
    if surface:
        clean = surface.strip()[:40]
        if clean:
            parts.append(f"Bề mặt UI: {clean}")
    if path:
        clean_path = path.strip()[:200]
        if clean_path and any(
            clean_path == prefix or clean_path.startswith(prefix + "/")
            for prefix in _ALLOWED_PATH_PREFIXES
        ):
            parts.append(f"Đường dẫn hiện tại (gợi ý hiển thị): {clean_path}")
    if plan_summary:
        summary = ", ".join(
            f"{item['count']} {item['category']}" for item in plan_summary
        )
        parts.append(f"Hạng mục bạn đã chốt trong kế hoạch cưới: {summary}")
    return "\n".join(parts) if parts else None


async def _generate_reply(content: str) -> str:
    """Generate an AI reply using the shared text-generation abstraction.

    Delegates provider selection to the sibling `chatbot.runtime` agent package.
    """
    from chatbot.runtime import generate_chat_reply

    return generate_chat_reply(content)


@router.post("/consult", response_model=ConsultResponse)
async def consult(
    body: ConsultRequest,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    client=Depends(get_supabase),
) -> ConsultResponse:
    """Anonymous-friendly couple consultant (tool-using agent + session memory)."""
    from chatbot.runtime import run_consultant_agent, sanitize_history
    from chatbot.session_store import get_session_store

    store = get_session_store()
    session_id, server_turns, _created = store.open(body.sessionId)

    if server_turns:
        turns = server_turns
    elif body.history:
        turns = sanitize_history([item.model_dump() for item in body.history])
    else:
        turns = []

    # FR-008: when the request carries a valid JWT, inject the caller's
    # accepted-plan summary (categories + counts, no PII) as extra context so
    # the agent can acknowledge existing choices and avoid re-suggesting them.
    plan_summary = None
    if user.user_id:
        plan_summary = await user_plan_repository.accepted_plan_summary(client, user.user_id)

    extra_context = _build_extra_context(
        path=body.path, surface=body.surface, plan_summary=plan_summary
    )
    reply, tools_used, retrieved = await run_consultant_agent(
        body.message,
        db=client,
        history=turns,
        extra_context=extra_context,
    )

    degraded = False
    if not (reply or "").strip():
        reply = _CONSULT_EMPTY_FALLBACK
        degraded = True

    store.append_turns(
        session_id,
        [
            {"role": "user", "content": body.message},
            {"role": "assistant", "content": reply},
        ],
    )

    cards = [card for row in retrieved if (card := _service_card(row)) is not None]
    logger.info(
        "consult_completed session_id=%s tools_used=%s services=%s degraded=%s",
        session_id,
        tools_used,
        len(cards),
        degraded,
    )
    return ConsultResponse(
        reply=reply,
        sessionId=session_id,
        retrievedServices=cards,
        toolsUsed=tools_used,
        degraded=degraded,
    )


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
