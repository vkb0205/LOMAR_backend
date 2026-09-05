"""Transport contracts for the Business Intelligence workspace."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AgentStatus = Literal["ready", "running", "completed", "approval_required"]
ActionStatus = Literal["preview", "approved", "dismissed"]


class BIMetric(BaseModel):
    label: str
    value: str
    change: str
    positive: bool = True


class BITrendPoint(BaseModel):
    label: str
    value: float


class BICategory(BaseModel):
    name: str
    amount: str
    share: str


class BIAgent(BaseModel):
    id: str
    name: str
    detail: str
    status: AgentStatus
    lastRun: str
    finding: str


class BIActivity(BaseModel):
    id: str
    title: str
    detail: str
    occurredAt: str
    kind: Literal["agent", "report", "action", "system"]


class BIRecommendation(BaseModel):
    id: str
    title: str
    detail: str
    impact: str
    actionLabel: str


class BIReport(BaseModel):
    id: str
    title: str
    period: str
    status: Literal["ready", "generating"]
    summary: str
    createdAt: str


class BIOverviewResponse(BaseModel):
    metrics: list[BIMetric]
    trend: list[BITrendPoint]
    categories: list[BICategory]
    agents: list[BIAgent]
    activities: list[BIActivity]
    recommendations: list[BIRecommendation]
    reports: list[BIReport]


class AgentRunRequest(BaseModel):
    agentId: str = Field(min_length=1, max_length=80)


class AgentRunResponse(BaseModel):
    agent: BIAgent
    activity: BIActivity


class ReportCreateRequest(BaseModel):
    period: str = Field(min_length=1, max_length=80)


class ReportCreateResponse(BaseModel):
    report: BIReport
    activity: BIActivity


class ActionPreviewRequest(BaseModel):
    recommendationId: str = Field(min_length=1, max_length=80)


class ActionPreviewResponse(BaseModel):
    recommendation: BIRecommendation
    status: ActionStatus
    message: str


class BIChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class BIChatResponse(BaseModel):
    reply: str
    sessionId: str | None = None
    activityIds: list[str] = Field(default_factory=list)
    recommendationIds: list[str] = Field(default_factory=list)
