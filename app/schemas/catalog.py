"""Catalog response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class VendorCard(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str = "Thương hiệu"
    category: str = "Khác"
    rating: float = 5.0
    addr: str = ""
    img: str = ""


class VendorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    vendor: dict[str, Any]
    services: list[dict[str, Any]]


class ServiceSuggestion(BaseModel):
    service: dict[str, Any]


class WeddingPlanCard(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    style: str | None = None
    minGuests: int = 0
    maxGuests: int = 0
    minBudget: float = 0
    maxBudget: float = 0
    currency: str = "VND"
    coverImageUrl: str | None = None
    description: str | None = None


class WeddingPlanDetailItemService(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    category: str | None = None
    vendorId: str | None = None


class WeddingPlanDetailItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    role: str
    sortOrder: int = 0
    quantity: int = 1
    unitPrice: float = 0
    currency: str = "VND"
    service: WeddingPlanDetailItemService


class WeddingPlanDetail(BaseModel):
    plan: WeddingPlanCard
    items: list[WeddingPlanDetailItem]
