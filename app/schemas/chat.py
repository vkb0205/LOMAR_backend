"""Chat transport models."""

from __future__ import annotations

from typing import Literal

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


class ChatThreadCreated(BaseModel):
    threadId: str


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1)


class ChatExchange(BaseModel):
    userMessage: ChatMessage
    assistantMessage: ChatMessage
    persisted: bool = True


class ConsultHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ConsultRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    sessionId: str | None = Field(default=None, max_length=128)
    history: list[ConsultHistoryMessage] = Field(default_factory=list, max_length=20)
    # optional trusted client context (path only — still treat as untrusted display hint)
    path: str | None = Field(default=None, max_length=200)
    surface: str | None = Field(default=None, max_length=40)


class RetrievedServiceCard(BaseModel):
    id: str
    name: str | None = None
    category: str | None = None
    basePrice: float | None = None
    currency: str | None = None
    thumbnailUrl: str | None = None
    vendorId: str | None = None


class ConsultResponse(BaseModel):
    reply: str
    sessionId: str
    retrievedServices: list[RetrievedServiceCard] = Field(default_factory=list)
    toolsUsed: list[str] = Field(default_factory=list)
    degraded: bool = False
