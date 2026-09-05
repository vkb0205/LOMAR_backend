"""Endpoints reserved for the exact LOMAR ``customer`` role."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.models import CurrentUser
from app.auth.permissions import require_customer
from app.routers.user_plan import router as user_plan_router
from .chat import router as chat_router
from .dashboard import router as dashboard_router

router = APIRouter(dependencies=[Depends(require_customer)])
account_router = APIRouter(prefix="/user", tags=["user"])


@account_router.get("/profile")
async def profile(user: Annotated[CurrentUser, Depends(require_customer)]) -> dict[str, str | None]:
    return {"id": user.id, "email": user.email, "role": user.role}


router.include_router(account_router)
router.include_router(dashboard_router)
router.include_router(chat_router)
router.include_router(user_plan_router)
