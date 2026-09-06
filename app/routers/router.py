"""Top-level API grouping by authentication and application role."""

from fastapi import APIRouter

from app.routers.admin import router as admin_router
from app.routers.business import router as vendor_router
from app.routers.public import router as public_router
from app.routers.user import router as user_router

router = APIRouter(prefix="/api/v1")
router.include_router(public_router)
router.include_router(user_router)
router.include_router(vendor_router)
router.include_router(admin_router)
