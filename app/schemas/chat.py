"""Chat transport models."""

from __future__ import annotations

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
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ConsultRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    sessionId: str | None = Field(default=None, max_length=200)
    history: list[ConsultHistoryMessage] = Field(default_factory=list, max_length=12)


class ConsultResponse(BaseModel):
    reply: str | None = None
    sessionId: str | None = None
    toolsUsed: list[str] = Field(default_factory=list)
    retrievedServices: list[dict] = Field(default_factory=list)
