"""Text generation provider abstraction.

Only the backend chat/consult paths call this. Image/VTON still uses
google-genai directly, so /health can continue preserving its existing
provider-shape behavior without picking one over the other.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.errors import UpstreamUnavailableError

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - provider selection happens at runtime
    OpenAI = None  # type: ignore[assignment,misc]

logger = logging.getLogger("app.ai_text")


def _openai_client() -> Any:
    if OpenAI is None:
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable (openai package missing)."
        )
    settings = get_settings()
    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key or None}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return OpenAI(**kwargs)


def generate_chat_reply(user_message: str) -> str:
    settings = get_settings()
    provider = (settings.ai_text_provider or "openai").strip().lower()
    text_model = settings.ai_text_model or settings.google_text_model or "gpt-4o-mini"

    if provider.startswith("google"):
        return _generate_google_reply(text_model, user_message)

    return _generate_openai_reply(text_model, user_message)


def _generate_google_reply(model: str, text: str) -> str:
    try:
        from google import genai  # type: ignore[import-untyped]
        from google.genai import types  # type: ignore[import-untyped]
    except Exception as exc:  # pragma: no cover
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable (google-genai missing)."
        ) from exc

    settings = get_settings()
    try:
        client = genai.Client(
            vertexai=settings.vertex_configured,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            api_key=settings.google_api_key or None,
        )
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=text)])],
            config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=512),
        )
    except Exception as exc:
        logger.exception("google_ai_generate_failed")
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable."
        ) from exc

    if not getattr(response, "candidates", None):
        return ""
    return "".join(p.text or "" for p in response.candidates[0].content.parts).strip()


def _generate_openai_reply(model: str, text: str) -> str:
    client = _openai_client()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": text}],
            temperature=0.7,
            max_tokens=512,
        )
    except Exception as exc:
        logger.exception("openai_generate_failed")
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable."
        ) from exc

    choice = (response.choices or [None])[0]
    if choice is None:
        return ""
    return (choice.message.content or "").strip()
