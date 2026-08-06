"""Catalog HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.deps.db import get_supabase
from app.errors import NotFoundError
from app.repositories import catalog as repository
from app.schemas.catalog import CustomizeCatalog, ServiceSuggestion, VendorCard, VendorDetail

router = APIRouter(prefix="/catalog", tags=["catalog"])


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
    images = await repository.list_service_images(client)
    vendors = await repository.list_all_vendors_for_customize(client)
    return CustomizeCatalog(services=services, serviceImages=images, vendors=vendors)


@router.get("/services/{serviceId}/suggestion", response_model=ServiceSuggestion)
async def service_suggestion(
    service_id: Annotated[str, Path(alias="serviceId", min_length=1)],
    client=Depends(get_supabase),
) -> ServiceSuggestion:
    service = await repository.get_service(client, service_id)
    if service is None:
        raise NotFoundError()
    return ServiceSuggestion(service=service)
