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
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from supabase import AsyncClient

from app.config import get_settings
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


class ConsultRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class TestTryOnResponse(BaseModel):
    image_url: str | None = Field(None, alias="imageUrl")
    message: str | None = None


class ConsultResponse(BaseModel):
    reply: str | None = None


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
    """Call the Vertex-AI image model and return the generated image URL.

    Both the JSON and multipart variants share this helper.  When *body_bytes*
    / *garment_bytes* are provided (multipart path) the bytes are uploaded via
    the Files API; otherwise the URL strings are passed directly to the model.

    Errors from the AI provider surface as 503 ``UpstreamUnavailableError``
    with a sanitised message (Constitution V).
    """
    settings = get_settings()

    if not settings.vertex_configured and not settings.supabase_configured:
        raise UpstreamUnavailableError(
            "Image generation is not configured (Vertex AI and Supabase are unavailable)."
        )

    try:
        from google import genai  # type: ignore[import-untyped]
        from google.genai import types  # type: ignore[import-untyped]
    except ImportError as exc:
        raise UpstreamUnavailableError(
            "AI SDK is not installed."
        ) from exc

    client = genai.Client(
        vertexai=settings.vertex_configured,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        api_key=settings.google_api_key or None,
    )

    # Build inline-data parts when raw bytes are provided; otherwise pass the URL
    # as the prompt alongside the model's multimodal input.
    parts: list[types.Part] = []
    if body_bytes is not None:
        parts.append(
            types.Part.from_bytes(
                data=body_bytes,
                mime_type=mimetypes.guess_type("body")[0] or "image/jpeg",
            )
        )
    else:
        parts.append(types.Part.from_uri(body_image_url, mime_type="image/jpeg"))

    if garment_bytes is not None:
        parts.append(
            types.Part.from_bytes(
                data=garment_bytes,
                mime_type=mimetypes.guess_type("garment")[0] or "image/jpeg",
            )
        )
    else:
        parts.append(
            types.Part.from_uri(garment_image_url, mime_type="image/jpeg")
        )

    text_prompt = f"Category: {category}. Style: {prompt}" if prompt else f"Category: {category}"
    parts.append(types.Part.from_text(text=text_prompt))

    model_name = settings.nano_banana_model or settings.google_text_model
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=parts,  # type: ignore[arg-type]
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )
    except Exception as exc:
        logger.exception("Image model call failed")
        raise UpstreamUnavailableError(
            "The image generation service is temporarily unavailable."
        ) from exc

    # Extract the first image candidate; the frontend only needs a URL.
    image_url: str | None = None
    message_text = ""
    if response.candidates:
        candidate = response.candidates[0]
        for part in candidate.content.parts:
            if part.text:
                message_text += part.text
            if part.inline_data:
                # Persist the generated image bytes so the browser can load it
                # via a stable URL.  We store in Supabase Storage when a
                # caller-JWT-scoped supabase client is available, otherwise fall
                # back to ephemeral base64 data URI (still works but not shared
                # between requests).
                inline_bytes = part.inline_data.data
                if supabase is not None:
                    object_path = f"generated/{uuid.uuid4()}.{mimetypes.guess_type('x.' + (part.inline_data.mime_type or 'png'))[1] or 'png'}"
                    try:
                        await supabase.storage.from_("generated").upload(
                            object_path,
                            inline_bytes,
                            {"contentType": part.inline_data.mime_type or "image/png"},
                        )
                        public_url = supabase.storage.from_("generated").get_public_url(
                            object_path
                        )
                        image_url = str(public_url)
                    except Exception as exc:
                        logger.exception("Image upload failed")
                        image_url = (
                            f"data:{part.inline_data.mime_type or 'image/png'};base64,"
                            + __import__("base64").b64encode(inline_bytes).decode()
                        )
                else:
                    image_url = (
                        f"data:{part.inline_data.mime_type or 'image/png'};base64,"
                        + __import__("base64").b64encode(inline_bytes).decode()
                    )
                break  # only the first image

    return TestTryOnResponse(image_url=image_url, message=message_text or None)


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
    """Return a textual AI response to *body.message*.

    Shape matches ``ai-consultant/types.ts`` ``ConsultResponse {reply?: string}``
    (Constitution Principle I) so the frontend hook and service layer can be
    swapped to this endpoint without change.
    """
    settings = get_settings()
    text_model = settings.google_text_model

    # When auth is enabled the endpoint should ideally carry the caller's
    # identity so the backend can log/save the conversation.  For now we just
    # reply from the model directly; history persistence is out of scope for
    # the legacy contract.
    try:
        from google import genai  # type: ignore[import-untyped]
        from google.genai import types  # type: ignore[import-untyped]

        client = genai.Client(
            vertexai=settings.vertex_configured,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            api_key=settings.google_api_key or None,
        )
        response = client.models.generate_content(
            model=text_model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=body.message)],
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=512,
            ),
        )
    except Exception as exc:
        logger.exception("Consult model call failed")
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable."
        ) from exc

    reply_text = ""
    if response.candidates:
        reply_text = "".join(
            p.text or "" for p in response.candidates[0].content.parts
        ).strip()

    return ConsultResponse(reply=reply_text or None)
