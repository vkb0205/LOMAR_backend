"""Catalog tools exposed to the AI consultant.

Design constraints (Constitution II/IV):

- **Narrow, not general.** There is deliberately no "run arbitrary SQL" or
  "read any table" tool. Each function answers one product-discovery question
  and nothing else. A model cannot reach a table that has no tool.
- **Allowlisted projection.** Every row is passed through an explicit field
  allowlist before it is handed to the model. ``vendors`` carries ``email``,
  ``phone`` and ``owner_id``; those are contact/PII columns that must never
  enter a model prompt, from where they could be echoed to any visitor.
  Allowlisting (rather than denylisting) means a future column added to the
  table is excluded by default instead of silently leaking.
- **Caller-scoped client.** Tools receive the request's RLS-preserving
  ``AsyncClient``. The service-role client is never used here, so the agent's
  reach is bounded by what the caller could already read.
- **Bounded output.** Row counts are capped by ``agent_tool_row_limit`` so a
  broad query cannot blow out the context window or the token bill.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from supabase import AsyncClient

from app.config import get_settings
from app.deps.db import run_db, unwrap
from app.errors import DatabaseUnavailableError

logger = logging.getLogger("app.agent_tools")

# Only `active` rows are public catalog (mirrors repositories/catalog.py).
VENDOR_VISIBLE_STATUS = "active"
SERVICE_VISIBLE_STATUS = "active"

# --- Field allowlists -------------------------------------------------------
# Anything not listed here is dropped before the model sees the row.
# NOTE: vendors.email / vendors.phone / vendors.owner_id are intentionally
# absent. Contact details are released by the application UI after a user
# action, not volunteered by a chatbot.
SERVICE_PUBLIC_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "category",
        "description",
        "base_price",
        "currency",
        "thumbnail_url",
        "vendor_id",
    }
)

VENDOR_PUBLIC_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "slug",
        "category",
        "description",
        "city",
        "image_url",
        "rating_avg",
        "rating_count",
    }
)


def _project(row: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    """Return only allowlisted, non-null fields from *row*."""
    return {k: v for k, v in row.items() if k in allowed and v is not None}


# Words too generic to narrow a wedding catalog; matching on them alone would
# return most of the table.
_QUERY_STOPWORDS: frozenset[str] = frozenset({"gói", "dịch", "vụ", "combo", "the", "và"})

# A single token cannot exceed this; keeps a pathological query from building a
# huge `or=` expression.
_MAX_QUERY_TOKENS = 6


def _build_or_expression(query: str) -> str:
    """Build a PostgREST `or=` expression matching ANY word in *query*.

    The previous implementation matched the whole phrase as one contiguous
    substring, so "váy cưới" could not find "Áo Dài Cưới Diệu Hỷ" — the phrase
    does not appear in that name. Vietnamese service names reorder and interleave
    these words freely, so per-token matching is what users actually expect.

    Matching is deliberately OR, not AND: a partial keyword overlap should still
    surface a candidate, and results are price-ordered and row-capped, so extra
    loose matches cost little. Callers that need precision pass `category`, which
    ANDs with this expression.

    Every token is stripped of PostgREST `or=` metacharacters (`,` `(` `)` `.`)
    and of LIKE wildcards (`%` `_`), so user text cannot alter the filter
    structure or widen the pattern.
    """
    tokens: list[str] = []
    for raw in query.split():
        token = raw
        for bad in (",", "(", ")", "."):
            token = token.replace(bad, " ")
        token = token.replace("%", r"\%").replace("_", r"\_").strip()
        if not token or token.lower() in _QUERY_STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
        if len(tokens) >= _MAX_QUERY_TOKENS:
            break

    # Every token was punctuation or a stopword: fall back to the whole string
    # so an all-stopword query does not silently become "match everything".
    if not tokens:
        cleaned = query
        for bad in (",", "(", ")", "."):
            cleaned = cleaned.replace(bad, " ")
        cleaned = cleaned.replace("%", r"\%").replace("_", r"\_").strip()
        if not cleaned:
            return ""
        tokens = [cleaned]

    clauses = []
    for token in tokens:
        clauses.append(f"name.ilike.%{token}%")
        clauses.append(f"description.ilike.%{token}%")
    return ",".join(clauses)


def _row_limit() -> int:
    return get_settings().agent_tool_row_limit


async def search_services(
    client: AsyncClient,
    *,
    query: str | None = None,
    category: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Find active services matching the couple's stated preferences."""
    capped = min(limit or _row_limit(), _row_limit())

    def _build() -> Any:
        q = (
            client.table("services")
            .select(",".join(sorted(SERVICE_PUBLIC_FIELDS)))
            .eq("status", SERVICE_VISIBLE_STATUS)
        )
        if category:
            # Case-insensitive: the model routinely emits a lowercased category
            # ("váy cưới") while the catalog stores title case ("Váy Cưới"), and
            # a case-sensitive eq() silently returns zero rows — indistinguishable
            # to the user from "we stock nothing in your budget". `ilike` without
            # wildcards is still a whole-value match, so this loosens casing only,
            # not the exactness of the category filter. Escaping `%` and `_` keeps
            # a model-supplied value from turning into a wildcard pattern.
            safe_category = category.strip().replace("%", r"\%").replace("_", r"\_")
            if safe_category:
                q = q.ilike("category", safe_category)
        if max_price is not None:
            q = q.lte("base_price", max_price)
        # A floor is ignored whenever a ceiling is present.
        #
        # Observed live: asked for "dưới 10 triệu" after a 5-triệu turn, the
        # model sent `min_price=5000000, max_price=10000000` — inferring a band
        # from the earlier budget. "Under X" never implies a floor, so that
        # silently hid the cheapest matching item, which is precisely what a
        # budget-conscious user is looking for. A schema description asking the
        # model not to do this did not hold; enforcement has to live here.
        #
        # Trade-off, accepted deliberately: a genuine "từ 5 đến 10 triệu" now
        # also returns everything under 10 triệu. Showing a few options that are
        # cheaper than asked is a far milder failure than concealing the one
        # affordable result.
        if min_price is not None and min_price > 0 and max_price is None:
            q = q.gte("base_price", min_price)
        elif min_price is not None and min_price > 0 and max_price is not None:
            logger.info(
                "agent_min_price_ignored min_price=%s max_price=%s",
                min_price,
                max_price,
            )
        if query:
            expression = _build_or_expression(query)
            if expression:
                q = q.or_(expression)
        return q.order("base_price", desc=False).limit(capped).execute()

    rows = unwrap(await run_db(_build)) or []
    return {
        "count": len(rows),
        "services": [_project(r, SERVICE_PUBLIC_FIELDS) for r in rows],
    }


async def search_vendors(
    client: AsyncClient,
    *,
    query: str | None = None,
    category: str | None = None,
    city: str | None = None,
    min_rating: float | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Find active vendors, optionally filtered by city, category or rating."""
    capped = min(limit or _row_limit(), _row_limit())

    def _build() -> Any:
        q = (
            client.table("vendors")
            .select(",".join(sorted(VENDOR_PUBLIC_FIELDS)))
            .eq("status", VENDOR_VISIBLE_STATUS)
        )
        if category:
            # Same casing hazard as search_services.
            safe_category = category.strip().replace("%", r"\%").replace("_", r"\_")
            if safe_category:
                q = q.ilike("category", safe_category)
        if city:
            q = q.ilike("city", f"%{city}%")
        if min_rating is not None:
            q = q.gte("rating_avg", min_rating)
        if query:
            expression = _build_or_expression(query)
            if expression:
                q = q.or_(expression)
        return q.order("rating_avg", desc=True).limit(capped).execute()

    rows = unwrap(await run_db(_build)) or []
    return {
        "count": len(rows),
        "vendors": [_project(r, VENDOR_PUBLIC_FIELDS) for r in rows],
    }


async def get_vendor_details(client: AsyncClient, *, vendor_id: str) -> dict[str, Any]:
    """Return one vendor plus the services they offer."""

    def _vendor() -> Any:
        return (
            client.table("vendors")
            .select(",".join(sorted(VENDOR_PUBLIC_FIELDS)))
            .eq("id", vendor_id)
            .eq("status", VENDOR_VISIBLE_STATUS)
            .execute()
        )

    vendor_rows = unwrap(await run_db(_vendor)) or []
    if not vendor_rows:
        return {"found": False, "reason": "No active vendor with that id."}

    limit = _row_limit()

    def _services() -> Any:
        return (
            client.table("services")
            .select(",".join(sorted(SERVICE_PUBLIC_FIELDS)))
            .eq("vendor_id", vendor_id)
            .eq("status", SERVICE_VISIBLE_STATUS)
            .limit(limit)
            .execute()
        )

    service_rows = unwrap(await run_db(_services)) or []
    return {
        "found": True,
        "vendor": _project(vendor_rows[0], VENDOR_PUBLIC_FIELDS),
        "services": [_project(r, SERVICE_PUBLIC_FIELDS) for r in service_rows],
    }


async def list_service_categories(client: AsyncClient) -> dict[str, Any]:
    """Distinct service categories available in the catalog.

    Lets the agent ground itself in real category names instead of inventing
    plausible-sounding ones.
    """

    def _build() -> Any:
        return (
            client.table("services")
            .select("category")
            .eq("status", SERVICE_VISIBLE_STATUS)
            .limit(500)
            .execute()
        )

    rows = unwrap(await run_db(_build)) or []
    categories = sorted({r["category"] for r in rows if r.get("category")})
    return {"categories": categories}


# --- Provider-facing schemas ------------------------------------------------
# OpenAI-compatible JSON Schema. `additionalProperties: false` keeps a model
# from smuggling unexpected keys into the dispatcher.
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_services",
            "description": (
                "Search active wedding services in the Phố Hạnh Phúc catalog by "
                "keyword, category and/or price range. Use this whenever the user "
                "describes what they want (e.g. 'áo dài dưới 5 triệu'). Prices are "
                "in the currency returned with each row."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Free-text keywords matched against service name and "
                            "description; a row matches if it contains ANY of the words. "
                            "OMIT this when you are already filtering by `category` — the "
                            "two are ANDed, and some listings have English or brand-only "
                            "names that share no word with the Vietnamese category, so a "
                            "redundant query silently hides them."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Category name from list_service_categories. Matching is "
                            "case-insensitive but otherwise exact, so the name must "
                            "correspond to a real category — if none fits, use `query` "
                            "instead of guessing."
                        ),
                    },
                    "min_price": {
                        "type": "number",
                        "description": (
                            "Minimum base price. Only meaningful when the user gave a "
                            "lower bound and NO upper bound (e.g. 'từ 20 triệu trở lên'). "
                            "It is ignored whenever max_price is also supplied, because "
                            "'dưới X' never implies a floor — so do not try to express a "
                            "price band with it. Never infer a floor from a budget "
                            "mentioned earlier in the conversation."
                        ),
                    },
                    "max_price": {
                        "type": "number",
                        "description": (
                            "Maximum base price — the user's budget, in the catalog "
                            "currency (VND). '5 triệu' means 5000000, not 5."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_vendors",
            "description": (
                "Search active vendors by keyword, category, city or minimum "
                "average rating. Use when the user asks about providers/studios "
                "rather than a specific service."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text keywords for vendor name/description."},
                    "category": {"type": "string", "description": "Exact vendor category."},
                    "city": {"type": "string", "description": "City name, partial match allowed."},
                    "min_rating": {
                        "type": "number",
                        "description": "Minimum average rating, 0-5.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vendor_details",
            "description": (
                "Fetch one vendor and the services they offer. Requires a vendor id "
                "obtained from a previous search — never guess an id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vendor_id": {"type": "string", "description": "Vendor UUID from a prior search result."},
                },
                "required": ["vendor_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_service_categories",
            "description": (
                "List the distinct service categories that actually exist in the "
                "catalog. Call this before filtering by category if you are unsure "
                "of the exact naming."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

# Explicit name -> implementation map. Dispatch consults this dict only, so a
# hallucinated tool name resolves to nothing rather than reaching getattr()
# on the module (which would expose every function defined here).
_DISPATCH: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "search_services": search_services,
    "search_vendors": search_vendors,
    "get_vendor_details": get_vendor_details,
    "list_service_categories": list_service_categories,
}


async def dispatch_tool(
    client: AsyncClient, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Execute tool *name*, returning a JSON-serialisable result.

    Errors are converted into a structured payload rather than raised, so one
    bad tool call lets the model recover and answer instead of failing the
    whole request. ``DatabaseUnavailableError`` is the exception: if the
    database is down the request genuinely cannot be served.
    """
    fn = _DISPATCH.get(name)
    if fn is None:
        logger.warning("agent_unknown_tool name=%s", name)
        return {"error": f"Unknown tool '{name}'."}

    if not isinstance(arguments, dict):
        return {"error": "Tool arguments must be a JSON object."}

    try:
        return await fn(client, **arguments)
    except DatabaseUnavailableError:
        raise
    except TypeError as exc:
        # Wrong/unexpected argument names from the model.
        logger.warning("agent_tool_bad_args name=%s detail=%s", name, exc)
        return {"error": f"Invalid arguments for '{name}': {exc}"}
    except Exception as exc:
        logger.exception("agent_tool_failed name=%s", name)
        return {"error": f"Tool '{name}' failed: {type(exc).__name__}"}
