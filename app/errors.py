"""Single error envelope + exception handlers (research.md R5).

Every failure the client can observe is emitted as:

    {"error": {"code": "<stable_code>", "message": "...", ...}}

Upstream/database detail never reaches the body (data-model.md invariant 9);
operators correlate via the `X-Correlation-Id` response header instead.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("lomar.errors")

CODE_UNAUTHENTICATED = "unauthenticated"
CODE_FORBIDDEN = "forbidden"
CODE_NOT_FOUND = "not_found"
CODE_VALIDATION_ERROR = "validation_error"
CODE_DATABASE_UNAVAILABLE = "database_unavailable"
CODE_UPSTREAM_UNAVAILABLE = "upstream_unavailable"
CODE_INTERNAL_ERROR = "internal_error"

_DEFAULT_MESSAGES = {
    CODE_UNAUTHENTICATED: "Authentication is required.",
    CODE_FORBIDDEN: "You do not have access to this resource.",
    CODE_NOT_FOUND: "The requested resource was not found.",
    CODE_VALIDATION_ERROR: "The request payload is invalid.",
    CODE_DATABASE_UNAVAILABLE: "The data service is temporarily unavailable.",
    CODE_UPSTREAM_UNAVAILABLE: "An upstream provider is temporarily unavailable.",
    CODE_INTERNAL_ERROR: "An unexpected error occurred.",
}


class ApiError(Exception):
    """Base class for every client-visible error."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = CODE_INTERNAL_ERROR

    def __init__(
        self,
        message: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
        internal_detail: str | None = None,
    ) -> None:
        self.message = message or _DEFAULT_MESSAGES.get(self.code, "Request failed.")
        self.extra = extra or {}
        # Never serialized. Logged server-side only.
        self.internal_detail = internal_detail
        super().__init__(self.message)

    def to_body(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        error.update(self.extra)
        return {"error": error}


class UnauthenticatedError(ApiError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = CODE_UNAUTHENTICATED


class ForbiddenError(ApiError):
    status_code = status.HTTP_403_FORBIDDEN
    code = CODE_FORBIDDEN


class NotFoundError(ApiError):
    """404 — also used to mask wrong-owner access (data-model.md invariant 3)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = CODE_NOT_FOUND


class ValidationError(ApiError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = CODE_VALIDATION_ERROR

    def __init__(
        self,
        message: str | None = None,
        *,
        fields: dict[str, str] | None = None,
        internal_detail: str | None = None,
    ) -> None:
        super().__init__(
            message,
            extra={"fields": fields or {}},
            internal_detail=internal_detail,
        )


class DatabaseUnavailableError(ApiError):
    """503 — the SC-005 "unavailable" contract the frontend renders."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = CODE_DATABASE_UNAVAILABLE


class UpstreamUnavailableError(ApiError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = CODE_UPSTREAM_UNAVAILABLE


def error_response(error: ApiError, correlation_id: str | None = None) -> JSONResponse:
    headers = {"X-Correlation-Id": correlation_id} if correlation_id else None
    return JSONResponse(status_code=error.status_code, content=error.to_body(), headers=headers)


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


_STATUS_CODE_MAP = {
    status.HTTP_401_UNAUTHORIZED: CODE_UNAUTHENTICATED,
    status.HTTP_403_FORBIDDEN: CODE_FORBIDDEN,
    status.HTTP_404_NOT_FOUND: CODE_NOT_FOUND,
    status.HTTP_422_UNPROCESSABLE_CONTENT: CODE_VALIDATION_ERROR,
    status.HTTP_503_SERVICE_UNAVAILABLE: CODE_DATABASE_UNAVAILABLE,
}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers guaranteeing the single envelope on every error path."""

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        correlation_id = _correlation_id(request)
        if exc.internal_detail:
            # Detail stays in logs, keyed by correlation ID (invariant 9).
            logger.warning(
                "api_error code=%s status=%s correlation_id=%s detail=%s",
                exc.code,
                exc.status_code,
                correlation_id,
                exc.internal_detail,
            )
        return error_response(exc, correlation_id)

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields: dict[str, str] = {}
        for issue in exc.errors():
            location = [str(part) for part in issue.get("loc", []) if part not in ("body", "query")]
            fields[".".join(location) or "body"] = str(issue.get("msg", "invalid"))
        return error_response(ValidationError(fields=fields), _correlation_id(request))

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _STATUS_CODE_MAP.get(exc.status_code, CODE_INTERNAL_ERROR)
        message = _DEFAULT_MESSAGES.get(code, "Request failed.")
        body = {"error": {"code": code, "message": message}}
        correlation_id = _correlation_id(request)
        headers = {"X-Correlation-Id": correlation_id} if correlation_id else None
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = _correlation_id(request)
        # Stack trace to logs only; the client gets a generic envelope so no
        # internal hostname or provider text leaks (Constitution IV).
        logger.exception("unhandled_error correlation_id=%s", correlation_id)
        return error_response(ApiError(), correlation_id)

    # Ensure jsonable_encoder stays imported for handlers that may extend the
    # envelope with model payloads.
    _ = jsonable_encoder
