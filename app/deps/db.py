"""Database dependency factories (T007).

Provides two Supabase clients:

- ``get_supabase``: caller-JWT-scoped (RLS-preserving), the default for every
  data operation. The anon key is sent as ``apikey`` and the caller's JWT as
  the ``Authorization`` bearer, so PostgREST evaluates RLS against the
  caller's ``auth.uid()`` (research.md R2).
- ``get_supabase_admin``: service-role client. MUST only be used for
  operations that provably cannot run under the caller's JWT. Every call site
  MUST carry a one-line justification comment (Constitution II).

Every Supabase call must be executed through :func:`run_db` so that a timeout
or connection failure surfaces as ``503 database_unavailable`` instead of
hanging the request (research.md R5, SC-005).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

import httpx
from fastapi import Request
from supabase import AsyncClient, create_async_client
from supabase.lib.client_options import AsyncClientOptions

from app.config import get_settings
from app.errors import DatabaseUnavailableError

logger = logging.getLogger("app.db")

T = TypeVar("T")

# Exceptions that mean "the data service did not answer in time / at all".
# Anything else is a genuine application error and must not be masked as 503.
_UNAVAILABLE_ERRORS: tuple[type[BaseException], ...] = (
    asyncio.TimeoutError,
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)


async def _create_client(url: str, key: str, *, bearer: str | None = None) -> AsyncClient:
    """Build a Supabase async client.

    ``bearer``, when supplied, is the caller's JWT and is sent as the
    ``Authorization`` header so RLS sees the caller's identity while ``key``
    remains the project's anon key.
    """
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    return await create_async_client(url, key, options=AsyncClientOptions(headers=headers))


async def run_db(operation: Callable[[], Awaitable[T]]) -> T:
    """Execute a Supabase operation under the configured timeout.

    Timeout/connection failures become ``503 database_unavailable``; the
    upstream text is logged, never returned (data-model.md invariant 9).
    """
    settings = get_settings()
    try:
        return await asyncio.wait_for(operation(), timeout=settings.supabase_timeout_seconds)
    except _UNAVAILABLE_ERRORS as exc:
        logger.warning("supabase_unavailable error=%s", type(exc).__name__)
        raise DatabaseUnavailableError(internal_detail=str(exc)) from exc


async def get_supabase(request: Request) -> AsyncClient:
    """Return the caller-JWT-scoped client for this request.

    Reuses the client bound by ``AuthMiddleware`` when present; otherwise
    builds an anonymous client (still subject to RLS) so that public endpoints
    work for unauthenticated callers (FR-006).
    """
    bound = getattr(request.state, "supabase", None)
    if bound is not None:
        return bound

    factory = getattr(request.app.state, "supabase_factory", None)
    if factory is not None:
        # Anonymous request under a test/embedded factory — still route
        # through the same deterministic adapter instead of a live client.
        return factory("")

    settings = get_settings()
    if not settings.supabase_configured:
        raise DatabaseUnavailableError(internal_detail="SUPABASE_URL/ANON_KEY not configured")

    token = getattr(request.state, "access_token", "") or None
    try:
        return await _create_client(settings.supabase_url, settings.supabase_anon_key, bearer=token)
    except Exception as exc:
        logger.exception("Failed to construct Supabase client")
        raise DatabaseUnavailableError(internal_detail=str(exc)) from exc


async def get_supabase_admin(request: Request) -> AsyncClient:
    """Return a service-role client (RLS bypassed).

    Only for operations that cannot run under the caller's JWT. Importers must
    justify each call site (Constitution II, research.md R2).
    """
    factory = getattr(request.app.state, "supabase_admin_factory", None)
    if factory is not None:
        # Test/embedded injection point — keeps CI offline (Constitution VI).
        return factory()

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        # Missing service-role config is a deployment error, not an auth
        # bypass: fail closed as "unavailable" rather than silently
        # downgrading to the anon key.
        raise DatabaseUnavailableError(
            internal_detail="SUPABASE_SERVICE_ROLE_KEY not configured"
        )
    try:
        return await _create_client(settings.supabase_url, settings.supabase_service_role_key)
    except Exception as exc:
        logger.exception("Failed to construct service-role Supabase client")
        raise DatabaseUnavailableError(internal_detail=str(exc)) from exc


def unwrap(result: Any) -> Any:
    """Return ``result.data`` from a PostgREST response."""
    return getattr(result, "data", None)
