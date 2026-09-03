"""Text generation provider abstraction and the AI consultant agent loop.

Only the backend chat/consult paths call this. Image/VTON still uses
google-genai directly, so /health can continue preserving its existing
provider-shape behavior without picking one over the other.

Two entry points:

- :func:`generate_chat_reply` — legacy single-turn completion, no tools.
  Retained so existing callers/tests keep working.
- :func:`run_consultant_agent` — the agent: system prompt + conversation
  history + bounded tool-calling against the Supabase catalog.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
from typing import Any

from supabase import AsyncClient

from app.config import get_settings
from app.errors import UpstreamUnavailableError
from app.services.agent_prompt import build_system_prompt
from app.services.agent_tools import TOOL_SPECS, dispatch_tool

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - provider selection happens at runtime
    OpenAI = None  # type: ignore[assignment,misc]

logger = logging.getLogger("app.ai_text")

# Roles a client is permitted to replay as conversation history. `system` is
# excluded on purpose: accepting it would let a browser rewrite the agent's
# instructions. `tool` is excluded because tool results must originate from
# this server's own dispatcher, never from the client.
_ALLOWED_HISTORY_ROLES = frozenset({"user", "assistant"})

# Defensive cap on a single history message. Long pasted blobs are a cheap way
# to push the real system prompt out of a model's attention.
_MAX_HISTORY_CHARS = 4000


def _openai_client() -> Any:
    if OpenAI is None:
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable (openai package missing)."
        )
    settings = get_settings()
    if not settings.openai_api_key:
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable (no text provider key configured)."
        )
    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key or None}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return OpenAI(**kwargs)


def _resolve_model() -> str:
    settings = get_settings()
    return settings.ai_text_model or settings.google_text_model or "gpt-4o-mini"


def sanitize_history(raw: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Normalise untrusted client-supplied history into safe message dicts.

    Drops unknown roles, coerces content to text, truncates oversized entries
    and keeps only the most recent N turns.
    """
    if not raw:
        return []

    settings = get_settings()
    cleaned: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        if role not in _ALLOWED_HISTORY_ROLES:
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        cleaned.append({"role": role, "content": text[:_MAX_HISTORY_CHARS]})

    limit = settings.agent_max_history_messages
    return cleaned[-limit:] if limit else []


# --- Legacy single-turn path ------------------------------------------------


def generate_chat_reply(user_message: str) -> str:
    settings = get_settings()
    provider = (settings.ai_text_provider or "openai").strip().lower()
    text_model = _resolve_model()

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
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=512,
                system_instruction=build_system_prompt(),
            ),
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
    settings = get_settings()
    client = _openai_client()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": text},
            ],
            temperature=0.7,
            max_tokens=512,
        )
    except Exception as exc:
        # Diagnostic context: the client-facing message stays sanitized, but the
        # server log records enough to tell an invalid key from an exhausted
        # balance from an unrecognized model name. Never log the API key itself.
        _log_provider_failure(exc, model, settings.openai_base_url)
        raise UpstreamUnavailableError(
            "The AI consultant is temporarily unavailable."
        ) from exc

    choice = (response.choices or [None])[0]
    if choice is None:
        return ""
    return (choice.message.content or "").strip()


def _log_provider_failure(exc: Exception, model: str, base_url: str) -> None:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    body = getattr(exc, "message", None) or str(exc)
    logger.error(
        "openai_generate_failed provider_status=%s model=%s base_url=%s detail=%s",
        status,
        model,
        base_url or "<default openai>",
        body,
    )
    logger.exception("openai_generate_failed traceback")


# --- Agent path -------------------------------------------------------------


def _serialize_tool_call(call: Any) -> dict[str, Any]:
    """Convert an SDK tool-call object into a plain assistant-message dict."""
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.function.name,
            "arguments": call.function.arguments or "{}",
        },
    }


def _result_row_count(result: dict[str, Any]) -> int | str:
    """Best-effort row count from a tool result, for observability.

    Tools return their payload under a tool-specific key (``services``,
    ``vendors``, ``categories``); ``count`` is preferred when present. Returns
    ``"n/a"`` rather than raising for shapes that carry no collection.
    """
    if not isinstance(result, dict):
        return "n/a"
    if "error" in result:
        return "error"
    if isinstance(result.get("count"), int):
        return result["count"]
    for key in ("services", "vendors", "categories"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return "n/a"


# The chat surfaces render replies as plain text (`whitespace-pre-wrap`, no
# markdown parser), so markup would otherwise reach the user as literal syntax.
# The system prompt asks for plain text, but formatting instructions are
# advisory — models drift back to markdown, especially when listing prices and
# echoing `thumbnail_url` as an image. This is the enforcement half of that rule.

# Markdown image `![alt](url)` and link `[text](url)` forms, matched first
# (before emphasis) because a nested `*` inside the caption must not be treated
# as emphasis. The `url` must not itself be a bare opening `)`... handled below.
_MEDIA_RE = re.compile(
    r"!\[([^\]]*)\]\(([^)\s]+)\)"
    r"|\[([^\]]+)\]\(([^)\s]+)\)"
)

# Bare http(s) URLs the model emitted outside of markdown (e.g. a pasted
# `thumbnail_url`). The card row already carries the image, so a raw URL in
# prose is noise for the user.
_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)

# Bold/italic emphasis wrappers, matched only after media/URL stripping so any
# `*` that was part of a caption is long gone. Two alternatives, bold before
# italic, so `**x**` is consumed as one bold span rather than as two italic
# spans. The inner text may not contain the delimiter character, which stops a
# match from running past its own closing marker and swallowing a later,
# unrelated marker.
_EMPHASIS_RE = re.compile(
    r"\*\*([^*]+)\*\*"
    r"|\*([^*\n]+)\*"
    r"|__([^_]+)__"
    r"|_([^_\n]+)_",
    re.DOTALL,
)


def strip_markdown_emphasis(text: str) -> str:
    """Remove markdown the UI cannot render, leaving plain text.

    Handles the three forms a model most often drifts into when the product
    card row is unavailable to it:

    - images: ``![alt](url)`` -> ``alt``
    - links: ``[text](url)`` -> ``text``
    - bold/italic: ``**x**`` / ``*x*`` -> ``x``
    - bare ``http(s)://`` URLs outside markdown -> removed

    Bullet hyphens, numbered lists and newlines are left intact because they
    render fine as plain text. Alt/link text is preserved, never dropped, so a
    caption like ``**Giá**`` survives as ``Giá`` after the image is unwrapped.
    """
    if not text:
        return text

    # Collapse `[alt](url)` into its caption text.
    text = _MEDIA_RE.sub(_media_replacement, text)
    # Drop any leftover bare URLs the model pasted outside markdown.
    text = _URL_RE.sub("", text)

    if "*" not in text and "_" not in text:
        return text

    previous = None
    # Nested emphasis (`**_x_**`) needs more than one pass; the loop is bounded
    # by the string shrinking on every iteration.
    while previous != text:
        previous = text
        # Exactly one alternative group matches per substitution; the rest are
        # None, so join the non-empty one.
        text = _EMPHASIS_RE.sub(lambda m: next(g for g in m.groups() if g is not None), text)
    return text


def _media_replacement(match: re.Match[str]) -> str:
    """Return the caption of a markdown image/link, trimmed of whitespace."""
    # Group 1 = image alt, Group 3 = link text; the other is None.
    caption = next((g for g in match.groups() if g is not None), "")
    return caption.strip()


# Fields the product-card row needs. A strict subset of SERVICE_PUBLIC_FIELDS,
# re-applied here so that widening the model-facing allowlist later does not
# silently start shipping new columns to the browser as well.
_CARD_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "category",
    "base_price",
    "currency",
    "thumbnail_url",
    "vendor_id",
)


def _collect_retrieved_services(
    result: dict[str, Any],
    sink: list[dict[str, Any]],
    seen: set[str],
) -> None:
    """Accumulate service rows from a tool result into *sink*, deduped by id.

    Handles three tool result shapes:

    - ``search_services`` / ``get_vendor_details`` return rows under a
      ``services`` key.
    - ``list_wedding_plans`` returns rows under a ``plans`` key; each plan maps
      onto the shared card shape (``style`` -> ``category``, ``min_budget`` ->
      ``base_price``, ``cover_image_url`` -> ``thumbnail_url``).
    - ``get_wedding_plan`` returns ``items``; each item's ``service`` is
      collected with the item's ``unit_price``/``currency`` as the card price.

    Vendor rows are ignored: the card row shows services only. Order is
    first-seen, which mirrors the tool's own price-ascending sort. A row without
    an ``id`` is skipped — the UI needs a stable React key and a link target,
    and neither can be synthesised safely.
    """
    if not isinstance(result, dict) or "error" in result:
        return

    if isinstance(result.get("plans"), list):
        for row in result["plans"]:
            if not isinstance(row, dict):
                continue
            identifier = row.get("id")
            if not isinstance(identifier, str) or identifier in seen:
                continue
            seen.add(identifier)
            sink.append(
                {
                    "id": identifier,
                    "name": row.get("name"),
                    "category": row.get("style"),
                    "base_price": row.get("min_budget"),
                    "currency": row.get("currency"),
                    "thumbnail_url": row.get("cover_image_url"),
                }
            )
        return

    if isinstance(result.get("items"), list):
        for item in result["items"]:
            if not isinstance(item, dict):
                continue
            service = item.get("service")
            if not isinstance(service, dict):
                continue
            identifier = service.get("id")
            if not isinstance(identifier, str) or identifier in seen:
                continue
            seen.add(identifier)
            card = {
                "id": identifier,
                "name": service.get("name"),
                "category": service.get("category"),
                "base_price": item.get("unit_price"),
                "currency": item.get("currency"),
                "thumbnail_url": service.get("thumbnail_url"),
                "vendor_id": service.get("vendor_id"),
            }
            sink.append({k: v for k, v in card.items() if v is not None})
        return

    rows = result.get("services")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get("id")
        if not isinstance(identifier, str) or identifier in seen:
            continue
        seen.add(identifier)
        sink.append({k: row[k] for k in _CARD_FIELDS if row.get(k) is not None})


def _parse_arguments(raw: str | None) -> dict[str, Any] | None:
    """Parse model-emitted JSON arguments, tolerating malformed output."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def run_consultant_agent(
    user_message: str,
    *,
    db: AsyncClient | None = None,
    history: list[dict[str, Any]] | None = None,
    extra_context: str | None = None,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Run the consultant with tool access.

    Returns ``(reply_text, tools_used, retrieved_services)``. ``tools_used`` is
    for observability. ``retrieved_services`` is the deduped set of catalog rows
    the tools actually returned this turn, so the UI can render product cards
    instead of asking the model to describe images or URLs in prose.

    ``extra_context`` is trusted, server-derived session context (e.g. the
    caller's accepted-plan summary) injected into the system prompt. It is
    never raw user input.

    Falls back to a plain completion when tools are disabled or no database
    client is available, so the consultant still answers rather than erroring.
    The fallback retrieves nothing, hence an empty card list.
    """
    settings = get_settings()
    provider = (settings.ai_text_provider or "openai").strip().lower()

    # Google's function-calling wire format differs; that path stays single-turn
    # until it is explicitly ported.
    if provider.startswith("google") or not settings.agent_tools_enabled or db is None:
        reply = await asyncio.to_thread(generate_chat_reply, user_message)
        return strip_markdown_emphasis(reply), [], []

    return await _run_openai_agent(
        user_message, db=db, history=history, extra_context=extra_context
    )


async def _run_openai_agent(
    user_message: str,
    *,
    db: AsyncClient,
    history: list[dict[str, Any]] | None,
    extra_context: str | None = None,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    settings = get_settings()
    model = _resolve_model()
    client = _openai_client()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(extra_context)},
        *sanitize_history(history),
        {"role": "user", "content": user_message},
    ]

    tools_used: list[str] = []
    retrieved_services: list[dict[str, Any]] = []
    seen_service_ids: set[str] = set()

    for iteration in range(settings.agent_max_tool_iterations):
        # Final iteration: withdraw the tools so the model is forced to answer
        # from what it has rather than looping until the cap and returning
        # nothing usable.
        is_last = iteration == settings.agent_max_tool_iterations - 1
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 800,
        }
        if not is_last:
            kwargs["tools"] = TOOL_SPECS
            kwargs["tool_choice"] = "auto"

        try:
            response = await asyncio.to_thread(
                functools.partial(client.chat.completions.create, **kwargs)
            )
        except Exception as exc:
            _log_provider_failure(exc, model, settings.openai_base_url)
            raise UpstreamUnavailableError(
                "The AI consultant is temporarily unavailable."
            ) from exc

        choice = (response.choices or [None])[0]
        if choice is None:
            return "", tools_used, retrieved_services

        message = choice.message
        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            reply = strip_markdown_emphasis((message.content or "").strip())
            return reply, tools_used, retrieved_services

        # Record the assistant turn verbatim; the provider requires each
        # tool result to reference a tool_call_id from a preceding message.
        messages.append(
            {
                "role": "assistant",
                "content": message.content or None,
                "tool_calls": [_serialize_tool_call(c) for c in tool_calls],
            }
        )

        for call in tool_calls:
            name = call.function.name
            arguments = _parse_arguments(call.function.arguments)
            if arguments is None:
                result: dict[str, Any] = {
                    "error": "Arguments were not valid JSON. Retry with a JSON object."
                }
            else:
                result = await dispatch_tool(db, name, arguments)
                tools_used.append(name)
                _collect_retrieved_services(result, retrieved_services, seen_service_ids)

            # Log the arguments and the row count, not just success/failure.
            # A search that returns zero rows is `ok=True`, so the old log line
            # could not distinguish "the model asked for the wrong thing" from
            # "the catalog genuinely has nothing" — the two failure modes that
            # look identical to a user reading "mình không tìm thấy...".
            # Arguments are model-authored search criteria (category, price,
            # keywords), not end-user PII, so they are safe to record.
            logger.info(
                "agent_tool_call name=%s iteration=%s ok=%s args=%s rows=%s",
                name,
                iteration,
                "error" not in result,
                json.dumps(arguments, ensure_ascii=False, default=str),
                _result_row_count(result),
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    # Cap exhausted without a text answer.
    logger.warning("agent_iteration_cap_reached tools_used=%s", tools_used)
    return "", tools_used, retrieved_services
