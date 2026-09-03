"""Application factory and ASGI entry point.

Mounts public health checks and the versioned ``/api/v1`` domain routers.  The
middleware chain, in registration order:

1. ``CorrelationIdMiddleware`` — injects/stores ``X-Correlation-Id``.
2. ``AuthMiddleware`` — verifies public and authenticated endpoint access,
   extracts the Bearer token, binds a caller-JWT Supabase client to
   ``request.state.supabase`` (used by ``require_admin``), and records the
   ``access_token`` for ``db.get_supabase``.

PUBLIC vs AUTHENTICATED endpoint policy (Constitution I, plus deviation #1):
    * ``/health`` and its ``/api/v1/health`` alias are **never gated by
      auth** and have **zero** upstream dependencies (Constitution III).
    * Explicitly public ``/api/v1`` prefixes (catalog reads, the blog feed,
      anonymous analytics tracking) accept unauthenticated callers per
      FR-006 / R4; when a token *is* supplied it is still verified and bound.
    * All other ``/api/v1/*`` endpoints **always require a valid Supabase
      JWT** regardless of ``ENABLE_AUTH``.
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
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import get_settings
from app.errors import ApiError, error_response, register_exception_handlers

logger = logging.getLogger("app.main")
from app.routers import health as health_router
from app.routers.admin import router as admin_router
from app.routers.analytics import router as analytics_router
from app.routers.business_intelligence import router as business_intelligence_router
from app.routers.catalog import router as catalog_router
from app.routers.chat import router as chat_router
from app.routers.dashboard import router as dashboard_router
from app.routers.social import router as social_router
from app.routers.user_plan import router as user_plan_router

# ---------------------------------------------------------------------------
# Correlation-ID middleware
# ---------------------------------------------------------------------------


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ensure every response carries ``X-Correlation-Id``."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        request.state.correlation_id = cid  # set before downstream middleware + error handlers need it
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Correlation-Id"] = cid
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Verify JWTs selectively based on ``ENABLE_AUTH``.

    The ``/api/v1`` tree requires a JWT for private routes and this middleware extracts
    whatever token is present (or leaves it absent) so that require_admin /
    require_user work uniformly.

    When a valid Bearer token is found we bind a caller-JWT Supabase async
    client to ``request.state.supabase`` so that ``require_admin`` and
    ``db.get_supabase(request_state=...)`` can both use the user's identity.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # AuthMiddleware is outside FastAPI's exception-handler boundary. Set the
        # correlation ID here too, then serialize auth errors directly so they
        # cannot escape as framework 500s.
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        try:
            settings = get_settings()
            path = request.url.path

            # /health (and its /api/v1 alias) are NEVER gated by auth and have
            # ZERO upstream dependencies (Constitution III, T006).
            if path in ("/health", "/api/v1/health"):
                request.state.supabase = None
                request.state.access_token = ""
                request.state.user_id = ""
                return await call_next(request)

            # Always-auth paths — /api/v1/* always require a JWT regardless of flag.
            always_auth = path.startswith("/api/v1/")
            public_v1 = (
                path.startswith("/api/v1/catalog/")
                or path == "/api/v1/posts"
                or path.startswith("/api/v1/analytics/page-views")
                or path == "/api/v1/chat/consult"
            )

            access_token: str = ""
            user_id: str = ""

            auth_required = always_auth and not public_v1
            if auth_required:
                from app.deps.auth import _extract_bearer, _decode_token
                from app.errors import UnauthenticatedError

                raw = _extract_bearer(request)
                if raw:
                    payload = _decode_token(raw)
                    access_token = raw
                    user_id = payload.sub
                else:
                    raise UnauthenticatedError("Authentication required.")
            else:
                # Optional identity: public endpoints still attribute a caller
                # when a valid token is supplied (feed like-state, analytics
                # user_id per invariant 10). An invalid token stays anonymous
                # rather than failing the public request.
                from app.deps.auth import _extract_bearer, _decode_token
                from app.errors import UnauthenticatedError

                raw = _extract_bearer(request)
                if raw:
                    try:
                        payload = _decode_token(raw)
                    except UnauthenticatedError:
                        pass
                    else:
                        access_token = raw
                        user_id = payload.sub

            # Bind a caller-JWT client for downstream code that needs it.
            state_supabase = None
            factory = getattr(request.app.state, "supabase_factory", None)
            if factory is not None:
                # Tests and embedded deployments may inject a deterministic
                # caller-scoped adapter without opening a live connection.
                state_supabase = factory(access_token)
            elif access_token and settings.supabase_configured:
                try:
                    from supabase import create_async_client
                    from supabase.lib.client_options import AsyncClientOptions

                    # RLS must see the CALLER's auth.uid(), so the anon key is
                    # the apikey and the caller JWT is the Authorization bearer
                    # (research.md R2 — caller-JWT path, RLS preserved).
                    state_supabase = await create_async_client(
                        settings.supabase_url,
                        settings.supabase_anon_key,
                        options=AsyncClientOptions(
                            headers={"Authorization": f"Bearer {access_token}"},
                        ),
                    )
                except Exception:
                    # Client construction is lazy in supabase-py; query failures
                    # are mapped by the database dependency/repository layer.
                    logger.exception("Failed to create Supabase client for request")
                    state_supabase = None

            request.state.supabase = state_supabase
            request.state.access_token = access_token
            request.state.user_id = user_id
            return await call_next(request)
        except ApiError as exc:
            return error_response(exc, correlation_id)


# ---------------------------------------------------------------------------
# FastAPI application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="LOMAR Backend API",
        version="1.0.0",
        # Disable /docs and /redoc when auth is off to avoid leaking internal
        # surface area; re-enable in production with ENABLE_AUTH=true.
        docs_url="/docs" if settings.enable_auth else None,
        redoc_url="/redoc" if settings.enable_auth else None,
    )

    # CORS — explicit allowlist only.
    origins = [o.strip() for o in settings.allowed_origins_list if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware chain — order matters. Auth also initializes correlation state
    # because it can reject a request before downstream middleware runs.
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(AuthMiddleware)

    # Register error envelope handlers last (they catch everything).
    register_exception_handlers(application)

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------

    # Public root health plus the versioned alias.
    application.include_router(health_router.router, prefix="", tags=["health"])
    application.include_router(health_router.router, prefix="/api/v1", tags=["health"])

    # Domain routers — prefix is /api/v1.
    application.include_router(catalog_router, prefix="/api/v1")
    application.include_router(dashboard_router, prefix="/api/v1")
    application.include_router(social_router, prefix="/api/v1")
    application.include_router(chat_router, prefix="/api/v1")
    application.include_router(analytics_router, prefix="/api/v1")
    application.include_router(business_intelligence_router, prefix="/api/v1")
    application.include_router(admin_router, prefix="/api/v1")
    application.include_router(user_plan_router, prefix="/api/v1")

    return application


# ---------------------------------------------------------------------------
# ASGI entry point
# ---------------------------------------------------------------------------

app = create_app()


def get_request_state(request: Request) -> dict:
    """Read-only accessor used by auth deps to pull bound state."""
    state = request.state
    return {
        "correlation_id": getattr(state, "correlation_id", ""),
        "access_token": getattr(state, "access_token", ""),
        "user_id": getattr(state, "user_id", ""),
        "supabase": getattr(state, "supabase", None),
    }


# ---------------------------------------------------------------------------
# Runner boilerplate
# ---------------------------------------------------------------------------

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
