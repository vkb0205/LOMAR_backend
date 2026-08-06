"""Chat transport models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    id: str
    role: str
    content: str
    createdAt: str
    suggestedServiceId: str | None = None


class ChatMessagesResponse(BaseModel):
    messages: list[ChatMessage]


class ChatThreadCreate(BaseModel):
    contextType: str = Field(default="consultant")
    vendorId: str | None = None
    serviceId: str | None = None
    designProjectId: str | None = None


class ChatThreadCreated(BaseModel):
    threadId: str


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1)


class ChatExchange(BaseModel):
    userMessage: ChatMessage
    assistantMessage: ChatMessage
    persisted: bool = True
