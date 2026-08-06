"""Nano Banana image generation (shopaikey ``/images/google/generations``).

A thin, validated wrapper over the documented HTTP contract (guide_img_api.md).
Kept separate from :mod:`app.services.ai_text` because it is a different
endpoint on a different host prefix with a different payload shape — the only
thing the two share is the API key.

The provider is called over plain ``httpx`` rather than the OpenAI SDK: this is
not an OpenAI-compatible route, so the SDK would buy nothing and obscure the
wire format.

Entry point: :func:`generate_image`.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import httpx

from app.config import get_settings
from app.errors import UpstreamUnavailableError, ValidationError

logger = logging.getLogger("app.ai_image")

# Path is fixed by the provider; only the host is configurable.
_GENERATIONS_PATH: Final = "/images/google/generations"

# Mirrors guide_img_api.md. Validated locally so a typo becomes a 422 naming the
# valid options, rather than an opaque upstream 400.
VALID_SIZES: Final[frozenset[str]] = frozenset(
    {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
)
VALID_IMAGE_SIZES: Final[frozenset[str]] = frozenset({"0.5K", "1K", "2K", "4K"})
VALID_FORMATS: Final[frozenset[str]] = frozenset({"png", "jpeg"})
VALID_RESPONSE_FORMATS: Final[frozenset[str]] = frozenset({"url", "b64_json"})

# `imageSize` is only meaningful for the newer models; nano-banana has a fixed
# output size and rejects the parameter.
_MODELS_SUPPORTING_IMAGE_SIZE: Final[frozenset[str]] = frozenset(
    {"nano-banana-2", "nano-banana-pro"}
)

# Per-model reference-image ceilings from the provider docs. The configured
# limit is applied on top of this, whichever is stricter.
_MODEL_REFERENCE_LIMITS: Final[dict[str, int]] = {
    "nano-banana": 3,
    "nano-banana-2": 5,
    "nano-banana-pro": 5,
}

# Upper bound on prompt length. The provider does not document one; this exists
# so an accidental multi-megabyte paste is rejected here instead of being
# billed upstream.
_MAX_PROMPT_CHARS: Final = 4000


def _validate_choice(value: str, allowed: frozenset[str], field: str) -> str:
    """Return *value* if permitted, else raise a 422 listing the valid options."""
    normalized = value.strip()
    if normalized not in allowed:
        raise ValidationError(
            f"{field} must be one of: {', '.join(sorted(allowed))}.",
            fields={field: normalized},
        )
    return normalized


def _validate_reference_urls(urls: list[str] | None, model: str) -> list[str]:
    """Validate caller-supplied reference image URLs.

    These are handed to the provider, which fetches them server-side. That
    makes them an SSRF vector by proxy, so they get the same private-address
    screening the local image proxy applies — reusing that checker rather than
    duplicating the ruleset so the two cannot drift apart.
    """
    if not urls:
        return []

    # Imported lazily: app.routers.vton imports service modules, so a top-level
    # import here would close an import cycle.
    from app.routers.vton import _is_url_safe

    settings = get_settings()
    provider_limit = _MODEL_REFERENCE_LIMITS.get(model, 3)
    limit = min(provider_limit, settings.image_max_reference_urls)

    if len(urls) > limit:
        raise ValidationError(
            f"At most {limit} reference images are allowed for {model}.",
            fields={"image_urls": str(len(urls))},
        )

    validated: list[str] = []
    for index, raw in enumerate(urls):
        url = (raw or "").strip()
        field = f"image_urls[{index}]"
        if not url:
            raise ValidationError("Reference image URL is empty.", fields={field: url})
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValidationError(
                "Reference image URL must be an absolute HTTP(S) URL.",
                fields={field: url},
            )
        if not _is_url_safe(url):
            raise ValidationError(
                "Reference image URL points at a blocked address.",
                fields={field: url},
            )
        validated.append(url)
    return validated


def _build_payload(
    *,
    prompt: str,
    model: str,
    size: str,
    image_size: str,
    fmt: str,
    response_format: str,
    reference_urls: list[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "format": fmt,
        "response_format": response_format,
    }
    # Sending imageSize to a model that does not accept it is a provider-side
    # 400, so it is omitted rather than defaulted.
    if model in _MODELS_SUPPORTING_IMAGE_SIZE:
        payload["imageSize"] = image_size
    if reference_urls:
        payload["image_urls"] = reference_urls
    return payload


def _extract_result(body: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pull ``(url, b64_json)`` out of a success response.

    The documented shape is ``{"created": ..., "data": [{...}]}`` with either
    key present depending on ``response_format``. Both are returned so the
    caller can pass through whichever the provider actually sent, instead of
    assuming the request's preference was honored.
    """
    data = body.get("data")
    if not isinstance(data, list) or not data:
        return None, None
    first = data[0]
    if not isinstance(first, dict):
        return None, None
    url = first.get("url")
    b64 = first.get("b64_json")
    return (
        url if isinstance(url, str) and url else None,
        b64 if isinstance(b64, str) and b64 else None,
    )


def _upstream_message(response: httpx.Response) -> str:
    """Best-effort extraction of the provider's error text, for logs only.

    Never surfaced to the client: it may carry upstream infrastructure detail
    (Constitution IV / errors.py invariant 9).
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:500]
    return str(body)[:500]


async def generate_image(
    prompt: str,
    *,
    model: str | None = None,
    size: str = "1:1",
    image_size: str = "2K",
    fmt: str = "png",
    response_format: str = "url",
    reference_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Generate an image from *prompt* and return ``{"url", "b64_json", "model"}``.

    Exactly one of ``url`` / ``b64_json`` is populated, matching whichever the
    provider returned. Raises :class:`ValidationError` (422) for bad input and
    :class:`UpstreamUnavailableError` (503) for any provider or transport
    failure, with the upstream text confined to server logs.
    """
    settings = get_settings()

    if not settings.image_generation_configured:
        # Distinct from a transport failure: nothing was attempted. Logged at
        # error level because it is a deployment mistake, not a runtime blip.
        logger.error(
            "image_generation_not_configured base_url_set=%s key_set=%s",
            bool(settings.image_api_base_url),
            bool(settings.image_api_key_resolved),
        )
        raise UpstreamUnavailableError(
            "Image generation is not configured."
        )

    text = (prompt or "").strip()
    if not text:
        raise ValidationError("prompt must be provided.", fields={"prompt": ""})
    if len(text) > _MAX_PROMPT_CHARS:
        raise ValidationError(
            f"prompt exceeds {_MAX_PROMPT_CHARS} characters.",
            fields={"prompt": str(len(text))},
        )

    resolved_model = (model or settings.image_model).strip()
    if not resolved_model:
        raise ValidationError("model must be provided.", fields={"model": ""})

    payload = _build_payload(
        prompt=text,
        model=resolved_model,
        size=_validate_choice(size, VALID_SIZES, "size"),
        image_size=_validate_choice(image_size, VALID_IMAGE_SIZES, "imageSize"),
        fmt=_validate_choice(fmt, VALID_FORMATS, "format"),
        response_format=_validate_choice(
            response_format, VALID_RESPONSE_FORMATS, "response_format"
        ),
        reference_urls=_validate_reference_urls(reference_urls, resolved_model),
    )

    endpoint = settings.image_api_base_url.rstrip("/") + _GENERATIONS_PATH

    try:
        async with httpx.AsyncClient(timeout=settings.image_timeout_seconds) as client:
            response = await client.post(
                endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.image_api_key_resolved}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "image_generation_transport_failed model=%s detail=%s", resolved_model, exc
        )
        raise UpstreamUnavailableError(
            "The image generation service is temporarily unavailable."
        ) from exc

    if response.status_code != 200:
        # Status and provider text to logs, generic envelope to the client.
        # 401 (bad key) and 400 (bad params) are operator problems that are
        # indistinguishable to the end user, so they log distinctly here.
        logger.error(
            "image_generation_failed status=%s model=%s detail=%s",
            response.status_code,
            resolved_model,
            _upstream_message(response),
        )
        raise UpstreamUnavailableError(
            "The image generation service is temporarily unavailable."
        )

    try:
        body = response.json()
    except ValueError as exc:
        logger.error("image_generation_bad_json model=%s", resolved_model)
        raise UpstreamUnavailableError(
            "The image generation service returned an unreadable response."
        ) from exc

    url, b64 = _extract_result(body if isinstance(body, dict) else {})
    if url is None and b64 is None:
        # HTTP 200 with no usable image. Treated as an upstream failure rather
        # than returning an empty success the caller has to re-check.
        logger.error(
            "image_generation_empty_result model=%s keys=%s",
            resolved_model,
            sorted(body.keys()) if isinstance(body, dict) else type(body).__name__,
        )
        raise UpstreamUnavailableError(
            "The image generation service returned no image."
        )

    logger.info(
        "image_generation_ok model=%s size=%s format=%s refs=%d returned=%s",
        resolved_model,
        payload["size"],
        payload["format"],
        len(payload.get("image_urls", [])),
        "url" if url else "b64_json",
    )
    return {"url": url, "b64_json": b64, "model": resolved_model}
