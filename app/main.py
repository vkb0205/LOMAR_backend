"""LOMAR FastAPI application composition.

Routes are assembled under ``app.routers`` into four explicit boundaries:
public, customer, vendor, and admin. Authentication and role authorization live
on FastAPI dependencies attached to those groups; middleware is reserved for
cross-cutting request concerns.

The retired Legacy VTON router is intentionally not imported or mounted.
"""

from __future__ import annotations

# Ensure the vendored agent packages (chatbot, business_intelligence) are
# importable as top-level modules. They live under app/agents/ and are imported
# as bare `chatbot` / `business_intelligence` by the routers and service shims.
# This works both locally and in the Docker image (app/agents is always inside
# the repo), unlike the previous sibling ../agents path that only existed in
# some local checkouts.
import sys
from pathlib import Path as _Path

_agents = _Path(__file__).resolve().parent / "agents"
if _agents.is_dir() and str(_agents) not in sys.path:
    sys.path.insert(0, str(_agents))

import logging
import time
import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import get_settings
from app.errors import register_exception_handlers
from app.routers.public import health as health_router
from app.routers.router import router as api_v1_router

logger = logging.getLogger("app.main")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach one traceable correlation ID to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = correlation_id
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="LOMAR Backend API",
        version="1.0.0",
        docs_url="/docs" if settings.enable_auth else None,
        redoc_url="/redoc" if settings.enable_auth else None,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(application)
    # Infrastructure liveness stays public at the conventional root path.
    application.include_router(health_router.router, tags=["health"])
    application.include_router(api_v1_router)
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )
