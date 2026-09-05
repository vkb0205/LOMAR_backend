"""Catalog HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.deps.db import get_supabase
from app.errors import NotFoundError
from app.repositories import catalog as repository
from app.schemas.catalog import (
    CustomizeCatalog,
    ServiceSuggestion,
    VendorCard,
    VendorDetail,
    WeddingPlanCard,
    WeddingPlanDetail,
    WeddingPlanDetailItem,
    WeddingPlanDetailItemService,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])

_WEDDING_PLAN_EMPTY_NAME = "Gói cưới"


@router.get("/vendors")
async def vendors(client=Depends(get_supabase)) -> dict[str, list[VendorCard]]:
    rows = await repository.list_vendors(client)
    cards = [
        VendorCard(
            id=str(row.get("id", "")),
            name=row.get("name") or "Thương hiệu",
            category=row.get("category") or "Khác",
            rating=float(row.get("rating_avg") or 5.0),
            addr=row.get("address") or "",
            img=row.get("image_url") or "",
        )
        for row in rows
    ]
    return {"vendors": cards}


@router.get("/vendors/{vendorId}", response_model=VendorDetail)
async def vendor_detail(
    vendor_id: Annotated[str, Path(alias="vendorId", min_length=1)],
    client=Depends(get_supabase),
) -> VendorDetail:
    vendor = await repository.get_vendor(client, vendor_id)
    if vendor is None:
        raise NotFoundError()
    services = await repository.list_vendor_services(client, vendor_id)
    return VendorDetail(vendor=vendor, services=services)


@router.get("/customize", response_model=CustomizeCatalog)
async def customize_catalog(client=Depends(get_supabase)) -> CustomizeCatalog:
    services = await repository.list_services(client)
    vendors = await repository.list_all_vendors_for_customize(client)
    return CustomizeCatalog(services=services, vendors=vendors)


@router.get("/services/{serviceId}/suggestion", response_model=ServiceSuggestion)
async def service_suggestion(
    service_id: Annotated[str, Path(alias="serviceId", min_length=1)],
    client=Depends(get_supabase),
) -> ServiceSuggestion:
    service = await repository.get_service(client, service_id)
    if service is None:
        raise NotFoundError()
    return ServiceSuggestion(service=service)


def _plan_card(row: dict) -> WeddingPlanCard:
    return WeddingPlanCard(
        id=str(row.get("id", "")),
        name=row.get("name") or _WEDDING_PLAN_EMPTY_NAME,
        style=row.get("style"),
        minGuests=int(row.get("min_guests") or 0),
        maxGuests=int(row.get("max_guests") or 0),
        minBudget=float(row.get("min_budget") or 0),
        maxBudget=float(row.get("max_budget") or 0),
        currency=row.get("currency") or "VND",
        coverImageUrl=row.get("cover_image_url"),
        description=row.get("description"),
    )


def _plan_item(row: dict) -> WeddingPlanDetailItem:
    service = row.get("service") or {}
    return WeddingPlanDetailItem(
        id=str(row.get("id", "")),
        role=row.get("role") or "dịch vụ",
        sortOrder=int(row.get("sort_order") or 0),
        quantity=int(row.get("quantity") or 1),
        unitPrice=float(row.get("unit_price") or 0),
        currency=row.get("currency") or "VND",
        service=WeddingPlanDetailItemService(
            id=service.get("id") or row.get("service_id") or "",
            name=service.get("name"),
            category=service.get("category"),
            vendorId=service.get("vendor_id"),
        ),
    )


@router.get("/wedding-plans")
async def wedding_plans(client=Depends(get_supabase)) -> dict[str, list[WeddingPlanCard]]:
    rows = await repository.list_wedding_plans(client)
    return {"plans": [_plan_card(row) for row in rows]}


@router.get("/wedding-plans/{planId}", response_model=WeddingPlanDetail)
async def wedding_plan_detail(
    plan_id: Annotated[str, Path(alias="planId", min_length=1)],
    client=Depends(get_supabase),
) -> WeddingPlanDetail:
    plan = await repository.get_wedding_plan(client, plan_id)
    if plan is None:
        raise NotFoundError()
    items = await repository.list_wedding_plan_items(client, plan_id)
    return WeddingPlanDetail(plan=_plan_card(plan), items=[_plan_item(row) for row in items])
