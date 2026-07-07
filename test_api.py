import asyncio
import base64
import ipaddress
import os
import socket
import time
from io import BytesIO
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, HttpUrl
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

# --- Item 16 (auth): PyJWT is only required when ENABLE_AUTH=true. Imported
# lazily so the container can still boot in open (gated-beta) mode without the
# dependency installed.
try:
    import jwt  # PyJWT
    _PYJWT_AVAILABLE = True
except ImportError:  # pragma: no cover
    jwt = None
    _PYJWT_AVAILABLE = False

load_dotenv()

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "true").strip().lower() in {"1", "true", "yes", "on"}
NANO_BANANA_MODEL = os.getenv("NANO_BANANA_MODEL", os.getenv("GOOGLE_IMAGE_MODEL", "gemini-2.5-flash-image-preview")).strip()
# --- Item 23: text model for the /consult AI consultant endpoint ---
# Separate from the image VTON model above so text and image gen can use different
# Gemini variants/aliases without code changes.
GOOGLE_TEXT_MODEL = os.getenv("GOOGLE_TEXT_MODEL", "gemini-2.5-flash").strip()
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "3003"))

# --- Item 15: CORS allowlist from env (no longer "*") ---
# Parse comma-separated ALLOWED_ORIGINS; fall back to safe local dev defaults when unset/empty.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: List[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    ALLOWED_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]

# --- Item 16: Supabase JWT verification (implemented behind ENABLE_AUTH) ---
# When ENABLE_AUTH is a truthy value, the /test-try-on*, /proxy-image, and
# /consult endpoints require a valid Supabase access token in the
# `Authorization: Bearer <jwt>` header. The token is verified against
# SUPABASE_JWT_SECRET (HS256, audience "authenticated"). When falsy, those
# endpoints remain open and rely on the slowapi rate limiter alone
# (gated-beta mode). Frontend should send the user's session.access_token.
ENABLE_AUTH = os.getenv("ENABLE_AUTH", "false").strip().lower() in {"1", "true", "yes", "on"}
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()
# Supabase access tokens use the "authenticated" audience by default.
SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated").strip()

if ENABLE_AUTH and not _PYJWT_AVAILABLE:
    raise RuntimeError("ENABLE_AUTH=true but PyJWT is not installed. Add PyJWT to backend/requirements.txt.")
if ENABLE_AUTH and not SUPABASE_JWT_SECRET:
    raise RuntimeError("ENABLE_AUTH=true but SUPABASE_JWT_SECRET is not set. Copy it from the Supabase dashboard (Project Settings → API → JWT Secret).")

# --- Item 17: upload/input size & dimension guards ---
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB cap on uploaded/downloaded image payloads
MAX_IMAGE_DIMENSION = 4096          # 4096px cap on either image dimension

# --- Item 16: slowapi rate limiter keyed by client host ---
limiter = Limiter(key_func=get_remote_address, default_limits=[])

app = FastAPI(title="LOMAR Vertex AI Nano Banana VTON API", version="3.0.0")

# Register slowapi state, exception handler, and middleware for rate limiting.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class TryOnRequest(BaseModel):
    body_url: HttpUrl = Field(..., description="Presigned/public URL of the mannequin/base image")
    garment_url: HttpUrl = Field(..., description="Presigned/public URL of the selected dress/clothing image")
    category: str = Field("onepieces", pattern="^(tops|bottoms|onepieces|dress|clothes)$")
    prompt: Optional[str] = Field("", description="Optional user query for styling or further clothing edits")


# --- Item 23: request body for the AI consultant chat endpoint ---
# `message` is the user's free-text question; `context` is optional structured
# context (e.g. recent conversation, service category) forwarded to the LLM.
class ConsultRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="The user's question for the wedding AI consultant")
    context: Optional[str] = Field(None, max_length=8000, description="Optional extra context forwarded to the LLM")


def _build_consult_system_prompt() -> str:
    """Item 23: Vietnamese wedding consultant persona for the /consult LLM.

    Keeps the assistant scoped to Phố Hạnh Phúc's wedding-planning domain,
    answering in Vietnamese, and declines to give legal/medical/financial advice
    or non-wedding topics.
    """
    return (
        "Bạn là 'Bé Song Hỷ', trợ lý AI đám cưới của nền tảng Phố Hạnh Phúc, "
        "một sàn kết nối dịch vụ cưới tại Việt Nam. Nhiệm vụ của bạn là tư vấn "
        "thân thiện, ngắn gọn và hữu ích cho các cặp đôi đang chuẩn bị đám cưới "
        "về: váy cưới & vest, chụp ảnh studio, thiệp cưới, makeup, venue/nhà hàng, "
        "trang trí, hoa cưới, âm nhạc, lịch trình và ngân sách đám cưới.\n\n"
        "Quy tắc:\n"
        "- Luôn trả lời bằng tiếng Việt, giọng điệu ấm áp, lịch sự, xưng 'mình' / 'bạn'.\n"
        "- Nếu câu hỏi ngoài phạm vi cưới hỏi (y tế, pháp lý, tài chính cá nhân, chính trị…), "
        "từ chối khéo léo và gợi ý quay lại chủ đề đám cưới.\n"
        "- Không bịa dịch vụ cụ thể; nếu cần, khuyên người dùng duyệt danh mục trên Phố Hạnh Phúc.\n"
        "- Trả lời tối đa ~250 từ, súc tích, dễ đọc; đừng bịa ra số điện thoại hay địa chỉ."
    )


# --- Item 16 (auth): FastAPI dependency gating the sensitive endpoints.
# Returns the decoded JWT payload (dict) when ENABLE_AUTH=true, or `None` when
# auth is disabled (gated-beta mode). Wire `user = Depends(...)` into an
# endpoint to require a valid Supabase access token; the anon key (audience
# "apikey") is intentionally rejected because we enforce audience "authenticated".
def require_authenticated_user(request: Request) -> Optional[Dict[str, Any]]:
    if not ENABLE_AUTH:
        # Open mode (gated beta): auth disabled, rate limiter is the only barrier.
        return None

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header. Expected 'Bearer <jwt>'.",
        )

    token = auth_header.split(" ", 1)[1].strip()
    try:
        # Supabase signs access tokens with the project JWT secret using HS256.
        decoded = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=SUPABASE_JWT_AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Access token has expired.")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Access token audience is invalid.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Access token is invalid.")
    except Exception:
        # Defensive: never leak JWT internals to the client.
        raise HTTPException(status_code=401, detail="Access token could not be verified.")

    return decoded


def _bytes_to_data_url(content: bytes, content_type: str) -> str:
    content_type = (content_type or "image/png").split(";")[0]
    if not content_type.startswith("image/"):
        raise ValueError(f"Input did not contain an image. content-type={content_type}")

    encoded = base64.b64encode(content).decode("utf-8")
    return f"data:{content_type};base64,{encoded}"


def _normalize_image_bytes(content: bytes, content_type: str) -> Dict[str, Any]:
    content_type = (content_type or "image/png").split(";")[0]
    if not content_type.startswith("image/"):
        raise ValueError(f"Input did not contain an image. content-type={content_type}")

    try:
        with Image.open(BytesIO(content)) as image:
            # --- Item 17: enforce max image dimensions to limit abuse / resource use ---
            if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
                raise HTTPException(
                    status_code=422,
                    detail=f"Image dimensions {image.width}x{image.height} exceed the max allowed {MAX_IMAGE_DIMENSION}px",
                )
            image = ImageOps.exif_transpose(image).convert("RGB")
            output = BytesIO()
            image.save(output, format="PNG")
            png_bytes = output.getvalue()
    except HTTPException:
        raise
    except Exception as exc:
        raise ValueError(f"Could not decode image as a Vertex AI-compatible PNG: {exc}") from exc

    return {"bytes": png_bytes, "mime_type": "image/png", "data_url": _bytes_to_data_url(png_bytes, "image/png")}


def _is_url_allowed(url: str) -> bool:
    """--- Item 18: SSRF guard ---
    Return True only if `url` is http(s) and resolves exclusively to public IPs.
    Rejects private/loopback/link-local/reserved IPs and the cloud metadata endpoint.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Always block the cloud metadata endpoint regardless of how it is expressed.
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        # Explicitly block the GCP/AWS/Azure cloud metadata endpoint.
        if str(ip) == "169.254.169.254":
            return False
        # Reject any non-public (private/loopback/link-local/reserved) address.
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False

    return True


def _download_image(url: str) -> Dict[str, Any]:
    # --- Item 18: reject non-public / private-IP targets (SSRF) ---
    if not _is_url_allowed(url):
        raise HTTPException(status_code=403, detail="URL not allowed")

    # --- Item 20: run the sync requests.get in a thread so we don't block the event loop ---
    # (caller awaits via asyncio.to_thread)
    response = requests.get(url, timeout=30, stream=True)
    response.raise_for_status()

    # --- Item 17: streaming size cap to avoid unbounded downloads ---
    content_type = response.headers.get("content-type", "image/png")
    total = 0
    chunks: List[bytes] = []
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail=f"Downloaded image exceeds the max allowed {MAX_IMAGE_BYTES} bytes")
        chunks.append(chunk)
    content = b"".join(chunks)

    return _normalize_image_bytes(content, content_type)


async def _read_upload_image(upload: UploadFile) -> Dict[str, Any]:
    content = await upload.read()
    if not content:
        raise ValueError(f"{upload.filename or 'uploaded file'} is empty")
    # --- Item 17: enforce max upload size to avoid unbounded memory use ---
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"Uploaded image exceeds the max allowed {MAX_IMAGE_BYTES} bytes")
    return _normalize_image_bytes(content, upload.content_type or "image/png")


def _category_label(category: str) -> str:
    labels = {
        "tops": "upper-body top garment",
        "bottoms": "lower-body bottom garment",
        "onepieces": "one-piece dress or full-body garment",
        "dress": "dress",
        "clothes": "selected clothing item",
    }
    return labels[category]


def _build_vton_prompt(category: str, user_prompt: Optional[str]) -> str:
    garment_label = _category_label(category)
    extra_instruction = (user_prompt or "").strip()
    extra_block = f"\n\nUser styling/edit query:\n{extra_instruction}" if extra_instruction else ""

    return f"""
You are generating a virtual try-on image for a fashion UI.

Reference image 1: base mannequin image.
Reference image 2: selected dress/clothing image.

Task:
Put the {garment_label} from reference image 2 onto the mannequin from reference image 1. The result must look like a realistic product try-on photo.

Core requirements:
- Preserve the mannequin identity, body proportions, pose, camera angle, lighting direction, and background from reference image 1.
- Preserve the clothing design from reference image 2: color, fabric texture, pattern, neckline, sleeves, hem, silhouette, logos, embroidery, buttons, and visible construction details.
- Fit the clothing naturally on the mannequin with realistic drape, wrinkles, folds, shadows, occlusion, and perspective.
- Replace only the relevant clothing area for category "{category}".
- If the user query asks for refinements, apply them while keeping the mannequin and selected clothing recognizable.
- Do not add text, watermarks, labels, borders, UI controls, extra people, extra mannequins, or unrelated accessories.
- Return only the final edited image.{extra_block}
""".strip()


def _create_vertex_client() -> genai.Client:
    if not GOOGLE_GENAI_USE_VERTEXAI:
        api_key = os.getenv("GOOGLE_API_KEY", os.getenv("GEMINI_API_KEY", "")).strip()
        if not api_key:
            raise HTTPException(status_code=500, detail="GOOGLE_API_KEY or GEMINI_API_KEY is required when GOOGLE_GENAI_USE_VERTEXAI=false")
        return genai.Client(api_key=api_key)

    if not GOOGLE_CLOUD_PROJECT:
        raise HTTPException(status_code=500, detail="GOOGLE_CLOUD_PROJECT is not configured in .env")

    return genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION)


def _extract_generated_image(response: Any) -> Dict[str, Any]:
    raw_parts: List[str] = []
    finish_reason_str = "UNKNOWN"

    if not getattr(response, "candidates", None):
        raise HTTPException(status_code=502, detail={"message": "Nano Banana response did not include candidates"})

    for candidate in response.candidates:
        # Check finish_reason to detect safety refusals / blocked content
        finish_reason = getattr(candidate, "finish_reason", None)
        finish_reason_str = str(finish_reason) if finish_reason is not None else "UNKNOWN"

        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            continue

        for part in parts:
            # --- Try inline_data first (generated image) ---
            inline_data = getattr(part, "inline_data", None)
            if inline_data and getattr(inline_data, "data", None):
                mime_type = getattr(inline_data, "mime_type", "image/png") or "image/png"
                image_bytes = inline_data.data
                if isinstance(image_bytes, str):
                    image_bytes = base64.b64decode(image_bytes)
                return {"image_url": _bytes_to_data_url(image_bytes, mime_type), "raw": raw_parts or None}

            # --- Try part.as_image() as a fallback for newer Gemini SDK ---
            try:
                as_image = part.as_image()
                if as_image is not None:
                    image_bytes = as_image
                    if isinstance(image_bytes, str):
                        image_bytes = base64.b64decode(image_bytes)
                    return {"image_url": _bytes_to_data_url(image_bytes, "image/png"), "raw": raw_parts or None}
            except Exception:
                pass

            # --- Collect text parts for diagnostics ---
            text = getattr(part, "text", None)
            if text:
                raw_parts.append(text)

    # Build detailed error including finish_reason and any safety ratings
    safety_info = None
    for candidate in response.candidates:
        sr = getattr(candidate, "safety_ratings", None)
        if sr:
            try:
                safety_info = [{"category": str(getattr(r, "category", "")), "probability": str(getattr(r, "probability", ""))} for r in sr]
            except Exception:
                safety_info = str(sr)
            break

    error_detail = {
        "message": "No image found in Nano Banana response",
        "text_parts": raw_parts,
        "finish_reason": finish_reason_str,
        "safety_ratings": safety_info,
    }
    raise HTTPException(status_code=502, detail=error_detail)


async def _run_vton(
    body_image: Dict[str, Any],
    garment_image: Dict[str, Any],
    category: str,
    user_prompt: Optional[str],
    started: float,
) -> Dict[str, Any]:
    try:
        client = _create_vertex_client()

        # --- Item 19: safety filters restored to default-ish levels ---
        # Previously BLOCK_NONE (fully disabled). Now BLOCK_ONLY_HIGH, the least
        # restrictive non-disabled threshold, so only clearly unsafe content is
        # blocked while normal fashion try-on edits are not flagged as dangerous.
        safety_settings = [
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
        ]

        # --- Item 20: generate_content is a sync call; run it in a worker thread ---
        # so it does not block the asyncio event loop while Vertex AI processes.
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=NANO_BANANA_MODEL,
            contents=[
                _build_vton_prompt(category, user_prompt),
                types.Part.from_bytes(data=body_image["bytes"], mime_type=body_image["mime_type"]),
                types.Part.from_bytes(data=garment_image["bytes"], mime_type=garment_image["mime_type"]),
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                safety_settings=safety_settings,
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        raise HTTPException(status_code=502, detail={"message": f"Vertex AI Nano Banana request failed: {exc}", "latency_ms": latency_ms}) from exc

    latency_ms = round((time.perf_counter() - started) * 1000)
    result = _extract_generated_image(response)
    return {
        "ok": True,
        "image_url": result["image_url"],
        "latency_ms": latency_ms,
        "latency_seconds": round(latency_ms / 1000, 2),
        "model": NANO_BANANA_MODEL,
        "provider": "vertex-ai" if GOOGLE_GENAI_USE_VERTEXAI else "google-ai-api-key",
        "project": GOOGLE_CLOUD_PROJECT if GOOGLE_GENAI_USE_VERTEXAI else None,
        "location": GOOGLE_CLOUD_LOCATION if GOOGLE_GENAI_USE_VERTEXAI else None,
        "category": category,
        "prompt": user_prompt or "",
        "raw": result["raw"],
    }


@app.get("/proxy-image")
@limiter.limit("10/minute")
async def proxy_image(
    url: str,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(require_authenticated_user),
):
    # --- Item 18: SSRF guard — reject private/loopback/metadata URLs ---
    if not _is_url_allowed(url):
        raise HTTPException(status_code=403, detail="URL not allowed")

    try:
        # --- Item 20: request sync call off the event loop via a worker thread ---
        response = await asyncio.to_thread(requests.get, url, timeout=30)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "image/png")
        return Response(content=response.content, media_type=content_type)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to proxy image: {exc}")


@app.get("/health")
def health() -> Dict[str, Any]:
    # --- Item 16: /health stays public and unrate-limited (intentionally no decorator) ---
    return {
        "ok": True,
        "service": "LOMAR Vertex AI Nano Banana VTON API",
        "model": NANO_BANANA_MODEL,
        "provider": "vertex-ai" if GOOGLE_GENAI_USE_VERTEXAI else "google-ai-api-key",
        "project": GOOGLE_CLOUD_PROJECT if GOOGLE_GENAI_USE_VERTEXAI else None,
        "location": GOOGLE_CLOUD_LOCATION if GOOGLE_GENAI_USE_VERTEXAI else None,
        "vertex_configured": bool(GOOGLE_CLOUD_PROJECT) if GOOGLE_GENAI_USE_VERTEXAI else False,
        "auth_enabled": ENABLE_AUTH,
    }


@app.post("/test-try-on")
# --- Item 16: rate limit on VTON endpoint keyed by client host ---
# NOTE: slowapi requires the Starlette `Request` to be named `request`, so the
# Pydantic body is bound to `payload` (wire contract: URL/method/body/response unchanged).
@limiter.limit("10/minute")
async def test_try_on(
    request: Request,
    payload: TryOnRequest,
    user: Optional[Dict[str, Any]] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    started = time.perf_counter()

    try:
        # --- Item 20: run sync _download_image (uses sync requests.get) in a worker thread ---
        body_image = await asyncio.to_thread(_download_image, str(payload.body_url))
        garment_image = await asyncio.to_thread(_download_image, str(payload.garment_url))
    except HTTPException:
        # --- Item 17/18: let 413/422/403 from validation/SSRF propagate with their status ---
        raise
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"Could not download input image: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _run_vton(body_image, garment_image, payload.category, payload.prompt, started)


@app.post("/test-try-on-upload")
# --- Item 16: rate limit on VTON upload endpoint keyed by client host ---
@limiter.limit("10/minute")
async def test_try_on_upload(
    request: Request,
    body_image: UploadFile = File(...),
    garment_image: UploadFile = File(...),
    category: str = Form("onepieces"),
    prompt: str = Form(""),
    user: Optional[Dict[str, Any]] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    if category not in {"tops", "bottoms", "onepieces", "dress", "clothes"}:
        raise HTTPException(status_code=400, detail="category must be one of: tops, bottoms, onepieces, dress, clothes")

    started = time.perf_counter()

    try:
        body_payload = await _read_upload_image(body_image)
        garment_payload = await _read_upload_image(garment_image)
    except HTTPException:
        # --- Item 17: let 413/422 size & dimension errors propagate with their status ---
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _run_vton(body_payload, garment_payload, category, prompt, started)


@app.post("/consult")
# --- Item 23: AI wedding consultant chat endpoint backed by a Gemini text model ---
# Accepts { message, context? } and returns a Vietnamese wedding-planning reply
# from the LLM. Same BLOCK_ONLY_HIGH safety posture as the VTON endpoint, and the
# sync generate_content call is offloaded to a worker thread (Item 20 pattern).
@limiter.limit("10/minute")
async def consult(
    request: Request,
    payload: ConsultRequest,
    user: Optional[Dict[str, Any]] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    started = time.perf_counter()

    # Build the user turn: the user's question plus any optional free-text context
    # forwarded by the caller (e.g. the active service category or recent turns).
    user_turn_parts: List[str] = [payload.message]
    if payload.context:
        user_turn_parts.append(f"\n[Bối cảnh]: {payload.context}")
    user_turn = "\n".join(user_turn_parts)

    try:
        client = _create_vertex_client()

        # --- Item 19: BLOCK_ONLY_HIGH safety posture (same as VTON) ---
        safety_settings = [
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
            types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH),
        ]

        # --- Item 20: generate_content is sync; run it in a worker thread ---
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GOOGLE_TEXT_MODEL,
            contents=[user_turn],
            config=types.GenerateContentConfig(
                system_instruction=_build_consult_system_prompt(),
                response_modalities=["TEXT"],
                safety_settings=safety_settings,
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        raise HTTPException(status_code=502, detail={"message": f"Vertex AI text request failed: {exc}", "latency_ms": latency_ms}) from exc

    # Extract the first text part from the response; surface a readable error if
    # the model returned no text (e.g. blocked by safety filters).
    reply_text = ""
    finish_reason_str = "UNKNOWN"
    try:
        if getattr(response, "candidates", None):
            for candidate in response.candidates:
                finish_reason = getattr(candidate, "finish_reason", None)
                finish_reason_str = str(finish_reason) if finish_reason is not None else "UNKNOWN"
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if not parts:
                    continue
                for part in parts:
                    text = getattr(part, "text", None)
                    if text:
                        reply_text = text.strip()
                        break
                if reply_text:
                    break
    except Exception:
        # leave reply_text empty; handled below
        pass

    if not reply_text:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "No text returned by the model (possibly blocked by safety filters)",
                "finish_reason": finish_reason_str,
            },
        )

    latency_ms = round((time.perf_counter() - started) * 1000)
    return {
        "ok": True,
        "reply": reply_text,
        "model": GOOGLE_TEXT_MODEL,
        "provider": "vertex-ai" if GOOGLE_GENAI_USE_VERTEXAI else "google-ai-api-key",
        "project": GOOGLE_CLOUD_PROJECT if GOOGLE_GENAI_USE_VERTEXAI else None,
        "location": GOOGLE_CLOUD_LOCATION if GOOGLE_GENAI_USE_VERTEXAI else None,
        "latency_ms": latency_ms,
        "latency_seconds": round(latency_ms / 1000, 2),
        "finish_reason": finish_reason_str,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("test_api:app", host=API_HOST, port=API_PORT, reload=True)
