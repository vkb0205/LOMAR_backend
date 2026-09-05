"""Admin + analytics transport models — validation ported from admin/schemas.ts."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AccountRole(str, Enum):
    customer = "customer"
    vendor = "vendor"
    admin = "admin"


class ApplicationRole(str, Enum):
    customer = "customer"
    vendor = "vendor"
    admin = "admin"


class VendorStatus(str, Enum):
    draft = "draft"
    active = "active"
    suspended = "suspended"


class ServiceStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class PostStatus(str, Enum):
    draft = "draft"
    published = "published"
    hidden = "hidden"


class CommentStatus(str, Enum):
    published = "published"
    hidden = "hidden"
    flagged = "flagged"


class ServiceRequestStatus(str, Enum):
    new = "new"
    contacted = "contacted"
    quoted = "quoted"
    booked = "booked"
    cancelled = "cancelled"
    closed = "closed"


class DiscountType(str, Enum):
    percentage = "percentage"
    fixed = "fixed"


class PlatformMetrics(BaseModel):
    users: int
    vendors: int
    vendorsPending: int
    services: int
    posts: int
    postsHidden: int
    commentsFlagged: int
    leads: int
    leadsNew: int


class RoleUpdate(BaseModel):
    role: AccountRole


class ApplicationRoleUpdate(BaseModel):
    role: ApplicationRole


class VendorStatusUpdate(BaseModel):
    status: VendorStatus


class ServiceStatusUpdate(BaseModel):
    status: ServiceStatus


class PostStatusUpdate(BaseModel):
    status: PostStatus


class CommentStatusUpdate(BaseModel):
    status: CommentStatus


class ServiceRequestStatusUpdate(BaseModel):
    status: ServiceRequestStatus


class JourneyTaskWrite(BaseModel):
    """Fields ported 1:1 from `journeyTaskInsertSchema` (admin/schemas.ts)."""

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    is_mandatory: bool = False
    display_order: int = Field(default=0, ge=0)
    active: bool = True


class JourneyTaskUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    is_mandatory: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
    active: bool | None = None


class VoucherWrite(BaseModel):
    """Fields ported 1:1 from `voucherInsertSchema` (admin/schemas.ts)."""

    vendor_id: str | None = None
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    discount_type: DiscountType
    discount_value: float = Field(ge=0)
    min_order_value: float | None = Field(default=None, ge=0)
    required_task_id: str | None = None
    starts_at: str | None = None
    expires_at: str | None = None
    max_redemptions: int | None = Field(default=None, gt=0)
    active: bool = True

    @model_validator(mode="after")
    def _percentage_cap(self) -> "VoucherWrite":
        if self.discount_type is DiscountType.percentage and self.discount_value > 100:
            raise ValueError("Percentage discount cannot exceed 100.")
        return self


class VoucherPartialWrite(BaseModel):
    vendor_id: str | None = None
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    discount_type: DiscountType | None = None
    discount_value: float | None = Field(default=None, ge=0)
    min_order_value: float | None = Field(default=None, ge=0)
    required_task_id: str | None = None
    starts_at: str | None = None
    expires_at: str | None = None
    max_redemptions: int | None = Field(default=None, gt=0)
    active: bool | None = None

    @model_validator(mode="after")
    def _percentage_cap(self) -> "VoucherPartialWrite":
        if (
            self.discount_type is DiscountType.percentage
            and self.discount_value is not None
            and self.discount_value > 100
        ):
            raise ValueError("Percentage discount cannot exceed 100.")
        return self


class AnalyticsSummary(BaseModel):
    views: int
    uniqueVisitors: int
    sessions: int
    avgDurationSeconds: int
    bounceRate: float


class ProfileNameRequest(BaseModel):
    """Batch request for resolving display names of user IDs."""

    user_ids: list[str] = Field(default_factory=list)


class WebsiteAnalytics(BaseModel):
    summary: AnalyticsSummary
    pages: list[dict[str, Any]]
    behaviours: list[dict[str, Any]]
    daily: list[dict[str, Any]]


class PageViewCreate(BaseModel):
    id: str
    sessionId: str
    visitorId: str
    pagePath: str = Field(min_length=1, max_length=500)
    pageTitle: str | None = Field(default=None, max_length=300)
    referrerHost: str | None = Field(default=None, max_length=255)


class PageEngagementCreate(BaseModel):
    sessionId: str
    visitorId: str
    durationSeconds: int = Field(ge=0, le=86400)
    maxScrollPercent: int = Field(ge=0, le=100)
