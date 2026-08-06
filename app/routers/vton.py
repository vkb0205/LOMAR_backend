"""Legacy VTON (Virtual Try-On) router.

Reproduces the five documented endpoints the frontend already calls verbatim
(Constitution Principle I) so that no frontend rewrite is required when the
service is first cut over to this backend.

Endpoints
---------
``GET /proxy-image?url=<encoded>``
    Validated proxy: fetches the target URL and streams it back with a
    safe ``Content-Type``.  Constrained by SSRF checks, size limits, and a
    bounded timeout (research.md R7, Constitution IV).

``POST /test-try-on``
    JSON body ``{ "body_image": "<url>", "garment_image": "<url>", "category": "<str>", "prompt": "<str>" }``.
    Calls the Nano Banana image model and returns the generated image URL
    plus an optional human-readable ``message``.

``POST /test-try-on-upload``
    ``multipart/form-data`` with fields ``body_image``, ``garment_image``,
    ``category``, ``prompt``.  Same AI path as ``/test-try-on`` but accepts
    raw ``UploadFile`` bodies instead of URLs.  Returns the same response
    shape so the frontend's response-parsing code is shared between both
    endpoints.

``POST /consult``
    ``{ "message": "<str>" }`` → ``{"reply": "<str>"}`` (or ``ConsultResponse``
    shape matching the frontend ``ConsultResponse {reply?: string}`` type
    from ``ai-consultant/types.ts``).
"""

from __future__ import annotations

import io
import logging
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from supabase import AsyncClient

from app.config import get_settings
from app.deps.db import get_supabase
from app.errors import UpstreamUnavailableError, ValidationError

router = APIRouter(tags=["vton"])
logger = logging.getLogger("app.vton")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestTryOnBody(BaseModel):
    body_image: str = Field(..., description="URL of the body/mannequin image")
    garment_image: str = Field(..., description="URL of the garment image")
    category: str = Field(..., description="Clothing category label")
    prompt: str = Field("", description="Additional style description")


class ConsultHistoryMessage(BaseModel):
    """One prior turn replayed by the client.

    Only `user` / `assistant` are accepted — see `sanitize_history`. The
    pattern is enforced here too so a bad role is a 422 rather than a
    silently dropped message.
    """

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=4000)


class ConsultRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    # Opaque server-issued id. Unknown/expired ids start a fresh session.
    sessionId: str | None = Field(default=None, min_length=1, max_length=128)
    # Backward-compatible bootstrap context. Once a valid session exists, the
    # server-side transcript is authoritative and this field is ignored.
    history: list[ConsultHistoryMessage] | None = Field(default=None, max_length=50)


class TestTryOnResponse(BaseModel):
    # `populate_by_name` matters: the field carries an alias, so without it
    # `TestTryOnResponse(image_url=...)` silently discards the value and
    # serializes `imageUrl: null` — which the frontend reports as "response did
    # not include an image URL". Accepting both spellings keeps construction by
    # field name working alongside alias-based serialization.
    model_config = ConfigDict(populate_by_name=True)

    image_url: str | None = Field(None, alias="imageUrl")
    message: str | None = None


class RetrievedService(BaseModel):
    """One catalog row backing a product card in the chat UI.

    Mirrors the card-facing subset of the tool projection. Prices stay numeric
    so the client can format them per locale rather than parsing a string.
    """

    id: str
    name: str | None = None
    category: str | None = None
    basePrice: float | None = None
    currency: str | None = None
    thumbnailUrl: str | None = None
    vendorId: str | None = None


class ConsultResponse(BaseModel):
    reply: str | None = None
    # Server-generated opaque id for the process-local prototype memory. The
    # client echoes it on the next turn to continue the conversation.
    sessionId: str
    # Observability only; the frontend contract ignores unknown fields.
    toolsUsed: list[str] = Field(default_factory=list)
    # Catalog rows the tools returned this turn. The UI renders these as cards
    # above the composer, which is why the reply text itself never needs to
    # carry image URLs or links.
    retrievedServices: list[RetrievedService] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_image_urls(body: TestTryOnBody) -> tuple[str, str]:
    """Validate and return the (body, garment) URLs."""

    def _validate(url: str, field: str) -> str:
        url = url.strip()
        if not url:
            raise ValidationError(f"{field} must be provided.", fields={field: url})
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValidationError(
                f"{field} must be an absolute HTTP(S) URL.", fields={field: url}
            )
        if not _is_url_safe(url):
            raise ValidationError(
                f"{field} points at a blocked address.", fields={field: url}
            )
        return url

    return _validate(body.body_image, "body_image"), _validate(
        body.garment_image, "garment_image"
    )


# SSRF-safe URL matcher: accept only http/https and block private/reserved IPv4 ranges
_SSRF_IPV4_RE = re.compile(
    r"^https?://(?:"
    r"(?:(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3})|"  # 10.x.x.x / 127.x.x.x
    r"(?:172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})|"  # 172.16-31.x.x
    r"(?:192\.168\.\d{1,3}\.\d{1,3})|"  # 192.168.x.x
    r"(?:169\.254\.\d{1,3}\.\d{1,3})|"  # 169.254.x.x link-local
    r"(?:0\.0\.0\.0)|"  # 0.0.0.0
    r"(?:(?:0{1,3}\.){3}0{1,3})"  # 0.0.0.0 style
    r")"
    r"(?::\d+)?(?:/|$)"  # optional port + root path
)


def _is_url_safe(url: str) -> bool:
    """Return ``True`` when *url* is not directed at a private/reserved address."""
    parsed = url.lower()
    return not bool(_SSRF_IPV4_RE.match(parsed))


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    summary="Liveness check",
    include_in_schema=True,
)
async def health() -> dict[str, object]:
    """Thin delegation to the canonical health router.  Kept here so a
    client hitting the legacy root path still receives the same response
    shape without requiring both routers to be mounted separately.
    """
    from app.routers.health import health as _health

    return (await _health()).model_dump()


# ---------------------------------------------------------------------------
# /proxy-image
# ---------------------------------------------------------------------------


@router.get("/proxy-image", summary="Validated image proxy")
async def proxy_image(
    request: Request,
    url: Annotated[str, Query(..., description="URL-encoded target image URL")],
) -> Response:
    """Fetch *url* (after URL-decoding) and stream it back with the detected
    content-type.  Blocked if *url* points at a private or reserved IP range
    (SSRF protection).
    """
    settings = get_settings()
    target_url = url.strip()
    if not _is_url_safe(target_url):
        raise ValidationError("URL points at a blocked address.", fields={"url": target_url})

    # Resolve a friendly content-type header
    content_type, _ = mimetypes.guess_type(target_url)
    if content_type is None:
        content_type = "application/octet-stream"

    try:
        import httpx

        async with httpx.AsyncClient(
            timeout=settings.proxy_image_timeout_seconds,
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                target_url,
                headers={"User-Agent": "LOMAR-Backend/1.0"},
            )
    except httpx.HTTPError as exc:
        logger.warning("proxy_image fetch failed for %s: %s", target_url, exc)
        raise UpstreamUnavailableError(
            "Unable to fetch the target image."
        ) from exc

    if resp.status_code != 200:
        raise UpstreamUnavailableError(
            f"Target returned HTTP {resp.status_code}."
        )

    body = resp.content
    if len(body) > settings.proxy_image_max_bytes:
        logger.warning(
            "proxy_image content too large: %d bytes (limit %d)",
            len(body),
            settings.proxy_image_max_bytes,
        )
        raise ValidationError(
            "Image exceeds maximum allowed size.",
            fields={"max_bytes": str(settings.proxy_image_max_bytes)},
        )

    return Response(
        content=body,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------------------
# Shared AI call helper
# ---------------------------------------------------------------------------


# Bucket holding both the uploaded reference images and the generated results.
# Must be public-read: the image provider fetches `image_urls` server-side from
# its own infrastructure, so a signed or RLS-gated object would 404 for them.
_STORAGE_BUCKET: Final = "generated"


async def _upload_reference(
    supabase: AsyncClient,
    raw: bytes,
    *,
    label: str,
    content_type: str = "image/png",
) -> str:
    """Store *raw* in the public bucket and return its public URL.

    The multipart endpoint receives raw bytes, but the provider only accepts
    reference images as URLs it can fetch itself (guide_img_api.md: `image_urls`
    is an array of URLs; `b64_json` is a *response* format, not an input). So
    the bytes must be given a publicly reachable address before we can call it.
    """
    extension = mimetypes.guess_extension(content_type) or ".png"
    object_path = f"references/{uuid.uuid4()}{extension}"
    try:
        await supabase.storage.from_(_STORAGE_BUCKET).upload(
            object_path,
            raw,
            {"contentType": content_type},
        )
        return str(supabase.storage.from_(_STORAGE_BUCKET).get_public_url(object_path))
    except Exception as exc:
        # Without a reachable URL the provider cannot see this image at all,
        # so this is fatal rather than degradable.
        logger.exception("reference_upload_failed label=%s", label)
        raise UpstreamUnavailableError(
            "Unable to prepare the images for generation."
        ) from exc


async def _persist_generated(
    supabase: AsyncClient | None, b64_data: str
) -> str:
    """Return a browser-loadable URL for a base64 image payload.

    Prefers durable storage; falls back to an inline data URI so a storage
    outage degrades the *sharability* of the result rather than failing the
    request outright.
    """
    import base64

    try:
        raw = base64.b64decode(b64_data)
    except Exception:
        # Undecodable payload: hand the string back as a data URI unchanged and
        # let the browser reject it, rather than 500ing here.
        return f"data:image/png;base64,{b64_data}"

    if supabase is not None:
        object_path = f"outputs/{uuid.uuid4()}.png"
        try:
            await supabase.storage.from_(_STORAGE_BUCKET).upload(
                object_path,
                raw,
                {"contentType": "image/png"},
            )
            return str(
                supabase.storage.from_(_STORAGE_BUCKET).get_public_url(object_path)
            )
        except Exception:
            logger.exception("generated_image_upload_failed")

    return f"data:image/png;base64,{b64_data}"


async def _run_image_model(
    supabase: AsyncClient | None,
    body_image_url: str,
    garment_image_url: str,
    category: str,
    prompt: str,
    *,
    body_bytes: bytes | None = None,
    garment_bytes: bytes | None = None,
) -> TestTryOnResponse:
    """Generate a try-on image and return a URL the browser can load.

    Routed through :mod:`app.services.ai_image` (shopaikey / Nano Banana),
    which is the provider this deployment is actually configured for. The
    previous implementation called Google GenAI directly and constructed its
    client *outside* any error handling, so an unconfigured key surfaced as an
    unhandled ``ValueError`` -> generic 500 instead of a diagnosable 503.

    Both variants share this helper. When *body_bytes* / *garment_bytes* are
    supplied (multipart path) they are first uploaded to public storage,
    because the provider fetches reference images by URL server-side.

    Provider failures surface as 503 ``UpstreamUnavailableError`` with a
    sanitised message (Constitution V).
    """
    from app.services.ai_image import generate_image

    reference_urls: list[str] = []

    if body_bytes is not None or garment_bytes is not None:
        if supabase is None:
            # Nothing to fail over to: without storage the bytes cannot be made
            # reachable by the provider. Explicit 503 beats a confusing
            # provider-side rejection.
            logger.error("try_on_upload_without_storage_client")
            raise UpstreamUnavailableError(
                "Image generation is not configured (storage is unavailable)."
            )
        if body_bytes is not None:
            reference_urls.append(
                await _upload_reference(supabase, body_bytes, label="body_image")
            )
        if garment_bytes is not None:
            reference_urls.append(
                await _upload_reference(supabase, garment_bytes, label="garment_image")
            )
    else:
        reference_urls = [
            url for url in (body_image_url, garment_image_url) if url and url.strip()
        ]

    # The first reference is the mannequin/body, the second the garment; saying
    # so explicitly stops the model from treating them as interchangeable style
    # references.
    instruction = (
        "Virtual try-on: dress the person or mannequin from the first reference "
        "image in the garment from the second reference image. Preserve the "
        f"body pose, proportions and background. Garment category: {category}."
    )
    if prompt and prompt.strip():
        instruction = f"{instruction} {prompt.strip()}"

    result = await generate_image(
        instruction,
        reference_urls=reference_urls,
        response_format="url",
    )

    image_url = result.get("url")
    if not image_url:
        b64 = result.get("b64_json")
        if b64:
            image_url = await _persist_generated(supabase, b64)

    if not image_url:
        # generate_image already raises when the provider returns nothing, so
        # reaching here means an unexpected shape rather than a known failure.
        logger.error("try_on_no_image_url model=%s", result.get("model"))
        raise UpstreamUnavailableError(
            "The image generation service returned no image."
        )

    return TestTryOnResponse(
        image_url=image_url,
        message="Bé Song đã tạo ảnh thử đồ từ mẫu bạn chọn.",
    )


# ---------------------------------------------------------------------------
# /test-try-on  (JSON body)
# ---------------------------------------------------------------------------


@router.post(
    "/test-try-on",
    response_model=TestTryOnResponse,
    summary="Virtual try-on from image URLs",
)
async def test_try_on(
    request: Request,
    body: TestTryOnBody,
) -> TestTryOnResponse:
    """Generate a try-on image from two remote image URLs.

    Constitution Principle I: response MUST include an image URL readable as
    ``imageUrl`` / ``image_url`` / ``output.imageUrl`` / ``output.image_url``
    and SHOULD include a human-readable ``message``.  The Pydantic model
    exposes ``image_url`` with ``alias="imageUrl"`` so serialisation produces
    both keys (FastAPI / Pydantic v2 renders both snake_case and alias keys).
    """
    body_url, garment_url = _parse_image_urls(body)
    supabase: AsyncClient | None = None

    # Bind a caller-JWT client when the auth middleware has attached one.
    state_supabase = getattr(request.state, "supabase", None)
    if state_supabase is not None:
        supabase = state_supabase

    return await _run_image_model(
        supabase=supabase,
        body_image_url=body_url,
        garment_image_url=garment_url,
        category=body.category,
        prompt=body.prompt,
    )


# ---------------------------------------------------------------------------
# /test-try-on-upload  (multipart)
# ---------------------------------------------------------------------------


@router.post(
    "/test-try-on-upload",
    response_model=TestTryOnResponse,
    summary="Virtual try-on from uploaded images",
)
async def test_try_on_upload(
    request: Request,
    body_image: Annotated[UploadFile, File(..., description="Body/mannequin image")],
    garment_image: Annotated[UploadFile, File(..., description="Garment image")],
    category: Annotated[str, Form(...)],
    prompt: str = Form(default=""),
) -> TestTryOnResponse:
    """Same as ``/test-try-on`` but accepts raw uploaded files.

    The fields MUST be named ``body_image``, ``garment_image``, ``category``,
    ``prompt`` to match the existing frontend FormData payload
    (Constitution Principle I).
    """
    settings = get_settings()

    # Size guard: read at most ``upload_max_bytes`` from each upload.
    body_bytes = await body_image.read()
    garment_bytes = await garment_image.read()

    for field_name, raw in (("body_image", body_bytes), ("garment_image", garment_bytes)):
        if len(raw) == 0:
            raise ValidationError(f"{field_name} is empty.", fields={field_name: ""})
        if len(raw) > settings.upload_max_bytes:
            raise ValidationError(
                f"{field_name} exceeds the upload size limit.",
                fields={field_name: str(len(raw))},
            )

    state_supabase = getattr(request.state, "supabase", None)
    supabase: AsyncClient | None = None
    if state_supabase is not None:
        supabase = state_supabase

    return await _run_image_model(
        supabase=supabase,
        body_image_url="",  # unused when bytes are provided
        garment_image_url="",
        category=category,
        prompt=prompt,
        body_bytes=body_bytes,
        garment_bytes=garment_bytes,
    )


# ---------------------------------------------------------------------------
# /consult
# ---------------------------------------------------------------------------


@router.post("/consult", response_model=ConsultResponse, summary="AI consultant chat")
async def consult(
    request: Request,
    body: ConsultRequest,
) -> ConsultResponse:
    """Run the AI wedding consultant against *body.message*.

    The response always returns a server-generated ``sessionId``. A valid id
    loads process-local memory; ``history`` only bootstraps a new or expired
    session for backward compatibility. Memory is anonymous, TTL-bound and
    lost on process restart, so it is suitable for the prototype only.

    The agent reads the public catalog through the caller-scoped (RLS-
    preserving) client, so an anonymous visitor's agent sees exactly what an
    anonymous visitor could already see. The service-role client is never used
    here.
    """
    from app.services.ai_text import run_consultant_agent, sanitize_history
    from app.services.session_store import get_session_store

    session_store = get_session_store()
    session_id, stored_history, is_new_session = session_store.open(body.sessionId)

    # Client history is accepted only as a bootstrap path. A valid session's
    # server-side transcript is authoritative; otherwise a browser could
    # silently replace or fork memory by replaying a different transcript.
    if is_new_session:
        raw_history = [m.model_dump() for m in body.history] if body.history else None
        history = sanitize_history(raw_history)
    else:
        history = sanitize_history(stored_history)

    # Catalog reads are best-effort: if Supabase is not configured the
    # consultant should still answer from the system prompt rather than 503.
    db: AsyncClient | None
    try:
        db = await get_supabase(request)
    except Exception:
        logger.warning("consult_db_unavailable falling back to promptonly reply")
        db = None

    try:
        reply_text, tools_used, retrieved = await run_consultant_agent(
            body.message, db=db, history=history
        )
    except UpstreamUnavailableError:
        raise
    except Exception as exc:
        logger.exception("Consult model call failed")
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable."
        ) from exc

    # Persist only successful model output. For a new session, preserve the
    # sanitized bootstrap transcript as well as this exchange. If the TTL
    # expires during a slow provider call, replace it with a fresh
    # server-issued id rather than recreating an arbitrary client-supplied id.
    exchange = [{"role": "user", "content": body.message}]
    if reply_text:
        exchange.append({"role": "assistant", "content": reply_text})
    turns_to_store = (history if is_new_session else []) + exchange
    if not session_store.append_turns(session_id, turns_to_store):
        session_id, _, _ = session_store.open(None)
        session_store.append_turns(session_id, exchange)

    # Tool rows use the catalog's snake_case column names; the HTTP contract is
    # camelCase. Mapping here keeps the database's naming out of the API.
    cards = [
        RetrievedService(
            id=row["id"],
            name=row.get("name"),
            category=row.get("category"),
            basePrice=row.get("base_price"),
            currency=row.get("currency"),
            thumbnailUrl=row.get("thumbnail_url"),
            vendorId=row.get("vendor_id"),
        )
        for row in retrieved
        if row.get("id")
    ]

    return ConsultResponse(
        reply=reply_text or None,
        sessionId=session_id,
        toolsUsed=tools_used,
        retrievedServices=cards,
    )
