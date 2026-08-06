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


class CustomizeCatalog(BaseModel):
    model_config = ConfigDict(extra="allow")

    services: list[dict[str, Any]]
    serviceImages: list[dict[str, Any]]
    vendors: list[dict[str, Any]]


class ServiceSuggestion(BaseModel):
    service: dict[str, Any]
