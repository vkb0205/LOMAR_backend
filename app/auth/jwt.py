"""Cryptographic verification of Supabase access tokens."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import get_settings
from app.errors import UnauthenticatedError

_ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "ES256", "EdDSA"})


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, lifespan=600)


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    """Verify signature, expiry, audience, issuer, and required claims."""
    settings = get_settings()
    try:
        algorithm = jwt.get_unverified_header(token).get("alg")
        kwargs: dict[str, Any] = {
            "audience": settings.supabase_jwt_audience,
            "options": {"require": ["sub", "exp", "aud"]},
        }
        if settings.supabase_issuer:
            kwargs["issuer"] = settings.supabase_issuer

        if algorithm == "HS256":
            if not settings.supabase_jwt_secret:
                raise UnauthenticatedError("JWT verification is not configured.")
            payload = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], **kwargs)
        elif algorithm in _ASYMMETRIC_ALGORITHMS:
            if not settings.supabase_jwks_endpoint:
                raise UnauthenticatedError("JWKS verification is not configured.")
            key = _jwks_client(settings.supabase_jwks_endpoint).get_signing_key_from_jwt(token)
            payload = jwt.decode(token, key.key, algorithms=[algorithm], **kwargs)
        else:
            raise UnauthenticatedError("Unsupported JWT signing algorithm.")
    except UnauthenticatedError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise UnauthenticatedError("Token expired.") from exc
    except (jwt.PyJWTError, ValueError) as exc:
        raise UnauthenticatedError("Invalid authentication credentials.") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise UnauthenticatedError("Invalid authentication credentials.")
    return payload
