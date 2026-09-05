"""Routes which deliberately opt out of authentication."""

from fastapi import APIRouter, Depends

from app.deps.db import get_supabase
from app.repositories import catalog
from .analytics import router as analytics_router
from .catalog import router as catalog_router
from .health import router as health_router
from .social import router as social_router

router = APIRouter()
explicit_public_router = APIRouter(prefix="/public", tags=["public"])


@explicit_public_router.get("/health")
async def public_health() -> dict[str, bool]:
    return {"ok": True}


@explicit_public_router.get("/services")
async def services(client=Depends(get_supabase)) -> dict[str, list[dict]]:
    return {"services": await catalog.list_services(client)}


@explicit_public_router.get("/vendors")
async def vendors(client=Depends(get_supabase)) -> dict[str, list[dict]]:
    return {"vendors": await catalog.list_vendors(client)}


# Public composition is explicit. Social writes keep their endpoint-level
# authentication dependencies while the read-only feed remains public.
router.include_router(explicit_public_router)
router.include_router(health_router, tags=["health"])
router.include_router(catalog_router)
router.include_router(social_router)
router.include_router(analytics_router)
