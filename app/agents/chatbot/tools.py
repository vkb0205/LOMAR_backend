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


# --- Canonical category registry --------------------------------------------
# The catalog stores a small, fixed set of `services.category` values. Free-text
# user wording almost never equals one of those values verbatim ("vest cưới dưới
# 10 triệu" names no stored category called "Vest Cưới" — the catalog stores
# "Vest"). The model is unreliable at mapping that wording onto the stored
# value, so the mapping is enforced here, in code, where it cannot be argued
# with. `search_services(category=...)` only ever receives one of these exact
# canonical values.
#
# Canonical name == the literal `services.category` value stored in the DB.
# Keys are lowercased for lookup.
SERVICE_CATEGORY_REGISTRY: dict[str, frozenset[str]] = {
    # canonical : aliases (lowercased, so matching is case/however-normalised)
    "vest": frozenset({"vest", "vest cưới", "áo vest", "suit", "com lê"}),
    "váy cưới": frozenset({"váy cưới", "váy", "đầm cưới", "wedding gown", "dress"}),
    "studio": frozenset({"studio", "chụp ảnh", "nhiếp ảnh", "photography", "chụp hình"}),
    "venue": frozenset({"venue", "nhà hàng", "địa điểm", "sảnh cưới"}),
    "make up": frozenset({"make up", "makeup", "trang điểm", "cô dâu make up"}),
    "planner": frozenset({"planner", "wedding planner", "tổ chức cưới", "điều phối"}),
    "trang trí": frozenset({"trang trí", "decor", "trang hoàng", "trang tri"}),
    "thiệp cưới": frozenset({"thiệp cưới", "thiệp", "invitation", "giấy mời"}),
    "trang sức": frozenset({"trang sức", "trang suc", "jewelry", "nhẫn", "phụ kiện"}),
    "sức khỏe": frozenset({"sức khỏe", "suc khoe", "health", "sức khoẻ"}),
    "khác": frozenset({"khác", "khac", "other"}),
}

# Canonical names exactly as stored in `services.category` (title-cased).
CANONICAL_SERVICE_CATEGORIES: frozenset[str] = frozenset(
    name.title() for name in SERVICE_CATEGORY_REGISTRY
)


def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace so alias matching is forgiving of case."""
    return " ".join(text.strip().lower().split())


def resolve_service_category(mention: str | None) -> str | None:
    """Return the canonical ``services.category`` value for *mention*.

    Returns ``None`` when *mention* does not map to a defined category — the
    caller (the agent) must then ask a clarifying question rather than guessing
    or falling back to keyword search across unrelated rows.
    """
    if not mention:
        return None
    norm = _normalise(mention)
    if not norm:
        return None
    # Exact alias hit first.
    for canonical, aliases in SERVICE_CATEGORY_REGISTRY.items():
        if norm in aliases or norm == canonical:
            return canonical.title()
    return None


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

    # Only a canonical category name is accepted. The model must obtain it from
    # `resolve_service_category`; a free-text value like "Vest Cưới" is never a
    # stored category and would silently return zero rows. Rejecting it here
    # forces the agent to resolve first instead of guessing.
    canonical_category: str | None = None
    if category:
        canonical_category = resolve_service_category(category)
        if canonical_category is None:
            return {
                "count": 0,
                "services": [],
                "error": (
                    f"'{category}' is not a defined catalog category. "
                    "Call resolve_service_category first and use the exact "
                    "category name it returns."
                ),
            }

    def _build() -> Any:
        q = (
            client.table("services")
            .select(",".join(sorted(SERVICE_PUBLIC_FIELDS)))
            .eq("status", SERVICE_VISIBLE_STATUS)
        )
        if canonical_category:
            # `ilike` without wildcards is a case-insensitive whole value match,
            # so this loosens casing only, not exactness. Escaping `%` and `_`
            # keeps a model-supplied value from becoming a wildcard.
            safe_category = canonical_category.replace("%", r"\%").replace("_", r"\_")
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


async def resolve_service_category_tool(
    client: AsyncClient, *, mention: str
) -> dict[str, Any]:
    """Map free-text user wording onto a canonical catalog category.

    The catalog stores a fixed set of category names (e.g. ``Vest``), but users
    phrase them loosely ("vest cưới", "áo vest"). This tool returns the exact
    canonical name to pass to ``search_services(category=...)``. When the
    mention does not map to a defined category, it returns ``found: false`` and
    the agent must ask a clarifying question — never guess a category or fall
    back to keyword search across unrelated rows.
    """
    canonical = resolve_service_category(mention)
    if canonical is None:
        return {
            "found": False,
            "mention": mention,
            "available": sorted(CANONICAL_SERVICE_CATEGORIES),
        }
    return {"found": True, "category": canonical, "mention": mention}


# --- Wedding-plan and accepted-plan tools -----------------------------------

# Only `active` plans are public catalog (mirrors repositories/catalog.py).
PLAN_VISIBLE_STATUS = "active"

# Allowlist for a wedding-plan row handed to the model. No PII, no status
# plumbing — just what the couple needs to compare curated packages.
PLAN_PUBLIC_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "description",
        "style",
        "min_guests",
        "max_guests",
        "min_budget",
        "max_budget",
        "currency",
        "cover_image_url",
    }
)

# Allowlist for an accepted-plan item surfaced to the model. Deliberately
# excludes vendor_id / email / any contact or ownership column.
ACCEPTED_PLAN_PUBLIC_FIELDS: frozenset[str] = frozenset(
    {
        "item_type",
        "service_id",
        "plan_id",
        "category",
        "service_name",
        "service_price",
        "plan_name",
    }
)


async def list_wedding_plans(
    client: AsyncClient,
    *,
    max_budget: float | None = None,
    min_guests: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List active curated wedding plans, price-ascending, optionally filtered."""
    capped = min(limit or _row_limit(), _row_limit())

    def _build() -> Any:
        q = (
            client.table("wedding_plans")
            .select(",".join(sorted(PLAN_PUBLIC_FIELDS)))
            .eq("status", PLAN_VISIBLE_STATUS)
        )
        if max_budget is not None:
            q = q.lte("min_budget", max_budget)
        if min_guests is not None:
            q = q.gte("max_guests", min_guests)
        return q.order("min_budget", desc=False).limit(capped).execute()

    rows = unwrap(await run_db(_build)) or []
    return {
        "count": len(rows),
        "plans": [_project(r, PLAN_PUBLIC_FIELDS) for r in rows],
    }


async def get_wedding_plan(
    client: AsyncClient, *, plan_id: str
) -> dict[str, Any]:
    """Return one active plan plus its resolved item services."""

    def _plan() -> Any:
        return (
            client.table("wedding_plans")
            .select(",".join(sorted(PLAN_PUBLIC_FIELDS)))
            .eq("id", plan_id)
            .eq("status", PLAN_VISIBLE_STATUS)
            .execute()
        )

    plan_rows = unwrap(await run_db(_plan)) or []
    if not plan_rows:
        return {"found": False, "reason": "No active wedding plan with that id."}

    def _items() -> Any:
        return (
            client.table("wedding_plan_items")
            .select("role,quantity,unit_price,currency,services(id,name,category,vendor_id)")
            .eq("wedding_plan_id", plan_id)
            .order("sort_order")
            .execute()
        )

    item_rows = unwrap(await run_db(_items)) or []
    items = []
    for row in item_rows:
        service = row.get("services") or {}
        items.append(
            {
                "role": row.get("role", ""),
                "quantity": row.get("quantity", 1),
                "unit_price": row.get("unit_price"),
                "currency": row.get("currency"),
                "service": _project(service, SERVICE_PUBLIC_FIELDS),
            }
        )
    return {
        "found": True,
        "plan": _project(plan_rows[0], PLAN_PUBLIC_FIELDS),
        "items": items,
    }


async def get_user_plan(
    client: AsyncClient, *, category: str | None = None
) -> dict[str, Any]:
    """Recall the caller's accepted plan (read-only, allowlisted).

    Reads the ``v_user_accepted_plan`` view, which is RLS-scoped to the caller
    and contains only accepted rows. Groups by category with counts so the agent
    can acknowledge existing choices without re-suggesting them.
    """

    def _build() -> Any:
        q = client.table("v_user_accepted_plan").select("*")
        if category:
            safe = category.strip().replace("%", r"\%").replace("_", r"\_")
            if safe:
                q = q.ilike("category", safe)
        return q.execute()

    rows = unwrap(await run_db(_build)) or []
    if not rows:
        return {"found": False, "groups": [], "count": 0}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        projected = _project(row, ACCEPTED_PLAN_PUBLIC_FIELDS)
        cat = projected.get("category") or "Khác"
        grouped.setdefault(cat, []).append(projected)

    groups = [
        {"category": cat, "count": len(items), "items": items}
        for cat, items in grouped.items()
    ]
    total = sum(g["count"] for g in groups)
    return {"found": True, "groups": groups, "count": total}


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
                            "Exact canonical category name returned by "
                            "resolve_service_category. NEVER invent or guess a "
                            "category — call resolve_service_category with the "
                            "user's wording first and pass back the exact "
                            "category it returns. A free-text value that is not "
                            "a defined category is rejected and returns zero rows."
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
    {
        "type": "function",
        "function": {
            "name": "resolve_service_category",
            "description": (
                "Map the user's free-text wording onto the exact canonical catalog "
                "category name. Users phrase categories loosely ('vest cưới', 'áo "
                "vest', 'chụp ảnh') while the catalog stores a fixed set of names "
                "('Vest', 'Studio', ...). Call this BEFORE search_services whenever "
                "the user names a category, then pass the returned category to "
                "search_services. If it returns found:false, ask the user a "
                "clarifying question — do not guess a category or search by keyword."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mention": {
                        "type": "string",
                        "description": "The user's wording for the category, verbatim.",
                    },
                },
                "required": ["mention"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_wedding_plans",
            "description": (
                "List active curated wedding packages (gói cưới), price-ascending. "
                "Use when the user asks about pre-packaged wedding plans or bundles "
                "rather than a single service. Optionally filter by budget or guest count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_budget": {
                        "type": "number",
                        "description": "Maximum plan min_budget, in VND.",
                    },
                    "min_guests": {
                        "type": "integer",
                        "description": "Minimum guest capacity the plan must reach.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wedding_plan",
            "description": (
                "Fetch one wedding plan and the services it bundles. Requires a plan "
                "id obtained from list_wedding_plans — never guess an id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "description": "Wedding plan UUID from a prior list result."},
                },
                "required": ["plan_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_plan",
            "description": (
                "Recall the caller's accepted wedding plan (services and packages "
                "they have already chosen). Use to acknowledge existing choices and "
                "avoid re-suggesting them. Optionally filter by category."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category to filter the accepted plan by.",
                    },
                },
                "additionalProperties": False,
            },
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
    "resolve_service_category": resolve_service_category_tool,
    "list_wedding_plans": list_wedding_plans,
    "get_wedding_plan": get_wedding_plan,
    "get_user_plan": get_user_plan,
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
