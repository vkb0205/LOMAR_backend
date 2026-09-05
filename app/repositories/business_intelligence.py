"""Business Intelligence repositories — caller-JWT scoped.

Vendor scope:
  * admin without vendor ownership → platform scope (vendor_id=None)
  * vendor → first owned vendor (vendors.owner_id = user_id)
  * admin who also owns a vendor → still platform scope for global BI
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import AsyncClient

from app.deps.db import run_db, unwrap

DEFAULT_AGENT_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "sales-analyst",
        "name": "Sales Analyst",
        "detail": "Finds demand patterns and pipeline growth opportunities",
        "enabled": True,
        "sort_order": 10,
    },
    {
        "id": "customer-insights",
        "name": "Customer Insights",
        "detail": "Segments interested customers and repeat demand",
        "enabled": True,
        "sort_order": 20,
    },
    {
        "id": "campaign-optimizer",
        "name": "Campaign Optimizer",
        "detail": "Monitors outreach quality and budget signals",
        "enabled": True,
        "sort_order": 30,
    },
    {
        "id": "operations-monitor",
        "name": "Operations Monitor",
        "detail": "Surfaces operational risks in the lead pipeline",
        "enabled": True,
        "sort_order": 40,
    },
]


async def resolve_vendor_scope(client: AsyncClient, *, user_id: str, role: str) -> str | None:
    """Return vendor_id for scoped queries, or None for platform/admin global."""
    if role == "admin":
        return None
    result = await run_db(
        lambda: client.table("vendors")
        .select("id")
        .eq("owner_id", user_id)
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    rows = unwrap(result) or []
    if not rows:
        return None
    return rows[0].get("id")


async def list_agent_definitions(client: AsyncClient) -> list[dict[str, Any]]:
    try:
        result = await run_db(
            lambda: client.table("bi_agent_definitions")
            .select("*")
            .eq("enabled", True)
            .order("sort_order")
            .execute()
        )
        rows = unwrap(result) or []
        if rows:
            return rows
    except Exception:
        pass
    return list(DEFAULT_AGENT_DEFINITIONS)


async def list_latest_runs(
    client: AsyncClient, *, vendor_id: str | None, agent_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not agent_ids:
        return {}
    try:
        query = client.table("bi_agent_runs").select("*").in_("agent_id", agent_ids)
        if vendor_id is None:
            query = query.is_("vendor_id", None)
        else:
            query = query.eq("vendor_id", vendor_id)
        result = await run_db(lambda: query.order("started_at", desc=True).limit(50).execute())
        rows = unwrap(result) or []
    except Exception:
        return {}
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        aid = row.get("agent_id")
        if aid and aid not in latest:
            latest[aid] = row
    return latest


async def list_activities(
    client: AsyncClient, *, vendor_id: str | None, limit: int = 20
) -> list[dict[str, Any]]:
    try:
        query = client.table("bi_activities").select("*")
        if vendor_id is None:
            # Admin platform view: all activities (RLS still applies).
            pass
        else:
            query = query.eq("vendor_id", vendor_id)
        result = await run_db(lambda: query.order("occurred_at", desc=True).limit(limit).execute())
        return unwrap(result) or []
    except Exception:
        return []


async def list_recommendations(
    client: AsyncClient, *, vendor_id: str | None
) -> list[dict[str, Any]]:
    try:
        # Vendor scope sees own + global (null); admin sees all.
        result = await run_db(
            lambda: client.table("bi_recommendations")
            .select("*")
            .eq("status", "open")
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        rows = unwrap(result) or []
    except Exception:
        return []
    if vendor_id is None:
        return rows
    return [r for r in rows if r.get("vendor_id") in (None, vendor_id)]


async def list_reports(
    client: AsyncClient, *, vendor_id: str | None, limit: int = 20
) -> list[dict[str, Any]]:
    try:
        query = client.table("bi_reports").select("*")
        if vendor_id is not None:
            query = query.eq("vendor_id", vendor_id)
        result = await run_db(lambda: query.order("created_at", desc=True).limit(limit).execute())
        return unwrap(result) or []
    except Exception:
        return []


async def get_recommendation(
    client: AsyncClient, recommendation_id: str
) -> dict[str, Any] | None:
    try:
        result = await run_db(
            lambda: client.table("bi_recommendations")
            .select("*")
            .eq("id", recommendation_id)
            .limit(1)
            .execute()
        )
        rows = unwrap(result) or []
        return rows[0] if rows else None
    except Exception:
        return None


async def insert_agent_run(
    client: AsyncClient,
    *,
    agent_id: str,
    vendor_id: str | None,
    triggered_by: str,
    status: str,
    finding: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "agent_id": agent_id,
        "vendor_id": vendor_id,
        "triggered_by": triggered_by,
        "status": status,
        "finding": finding,
        "started_at": now,
        "finished_at": now if status in ("completed", "failed", "approval_required") else None,
    }
    result = await run_db(
        lambda: client.table("bi_agent_runs").insert(payload).select("*").single().execute()
    )
    return unwrap(result) or payload


async def insert_activity(
    client: AsyncClient,
    *,
    vendor_id: str | None,
    title: str,
    detail: str,
    kind: str,
    created_by: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "vendor_id": vendor_id,
        "title": title,
        "detail": detail,
        "kind": kind,
        "occurred_at": now,
        "created_by": created_by,
    }
    result = await run_db(
        lambda: client.table("bi_activities").insert(payload).select("*").single().execute()
    )
    return unwrap(result) or payload


async def insert_report(
    client: AsyncClient,
    *,
    vendor_id: str | None,
    title: str,
    period: str,
    status: str,
    summary: str,
    payload: dict[str, Any],
    created_by: str,
) -> dict[str, Any]:
    row = {
        "vendor_id": vendor_id,
        "title": title,
        "period": period,
        "status": status,
        "summary": summary,
        "payload": payload,
        "created_by": created_by,
    }
    result = await run_db(
        lambda: client.table("bi_reports").insert(row).select("*").single().execute()
    )
    return unwrap(result) or row


async def fetch_metrics_rpc(
    client: AsyncClient, *, vendor_id: str | None, days: int = 7
) -> dict[str, Any] | None:
    try:
        result = await run_db(
            lambda: client.rpc(
                "get_vendor_bi_metrics",
                {"p_vendor_id": vendor_id, "p_days": days},
            ).execute()
        )
        data = unwrap(result)
        if isinstance(data, list) and data:
            data = data[0]
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _pipeline_value(row: dict[str, Any]) -> float:
    bmin = row.get("budget_min")
    bmax = row.get("budget_max")
    try:
        if bmin is not None and bmax is not None:
            return (float(bmin) + float(bmax)) / 2.0
        if bmax is not None:
            return float(bmax)
        if bmin is not None:
            return float(bmin)
    except (TypeError, ValueError):
        return 0.0
    return 0.0


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def compute_metrics_from_tables(
    client: AsyncClient, *, vendor_id: str | None, days: int = 7
) -> dict[str, Any]:
    """Python fallback when RPC is unavailable (FakeSupabase / empty DB)."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev_start = now - timedelta(days=days * 2)

    try:
        query = client.table("service_requests").select(
            "id,user_id,vendor_id,service_id,budget_min,budget_max,created_at"
        )
        if vendor_id is not None:
            query = query.eq("vendor_id", vendor_id)
        result = await run_db(lambda: query.execute())
        requests = unwrap(result) or []
    except Exception:
        requests = []

    service_ids = {r.get("service_id") for r in requests if r.get("service_id")}
    categories_by_service: dict[str, str] = {}
    if service_ids:
        try:
            sresult = await run_db(
                lambda: client.table("services")
                .select("id,category")
                .in_("id", list(service_ids))
                .execute()
            )
            for row in unwrap(sresult) or []:
                categories_by_service[row["id"]] = row.get("category") or "Other"
        except Exception:
            pass

    current: list[dict[str, Any]] = []
    previous: list[dict[str, Any]] = []
    for row in requests:
        ts = _parse_ts(row.get("created_at"))
        if ts is None:
            continue
        if ts >= start:
            current.append(row)
        elif prev_start <= ts < start:
            previous.append(row)

    def _agg(rows: list[dict[str, Any]]) -> tuple[int, float, int, int]:
        leads = len(rows)
        pipeline = sum(_pipeline_value(r) for r in rows)
        budgeted = sum(
            1 for r in rows if r.get("budget_min") is not None or r.get("budget_max") is not None
        )
        customers = len({r.get("user_id") for r in rows if r.get("user_id")})
        return leads, pipeline, budgeted, customers

    leads, pipeline, budgeted, customers = _agg(current)
    prev_leads, prev_pipeline, _, prev_customers = _agg(previous)

    # Daily trend
    day_counts: dict[str, float] = {}
    for i in range(days + 1):
        day = (start + timedelta(days=i)).date()
        day_counts[day.isoformat()] = 0.0
    for row in current:
        ts = _parse_ts(row.get("created_at"))
        if ts is None:
            continue
        key = ts.date().isoformat()
        if key in day_counts:
            day_counts[key] += 1.0
    trend = [
        {
            "label": datetime.fromisoformat(k).strftime("%d/%m"),
            "value": v,
        }
        for k, v in sorted(day_counts.items())
    ]

    cat_totals: dict[str, float] = {}
    for row in current:
        sid = row.get("service_id")
        name = categories_by_service.get(sid, "Other") if sid else "Other"
        cat_totals[name] = cat_totals.get(name, 0.0) + _pipeline_value(row)
    categories = [
        {"name": name, "pipeline_value": value}
        for name, value in sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
    ]

    return {
        "days": days,
        "leads": leads,
        "previousLeads": prev_leads,
        "pipelineValue": pipeline,
        "previousPipelineValue": prev_pipeline,
        "budgetedLeads": budgeted,
        "interestedCustomers": customers,
        "previousInterestedCustomers": prev_customers,
        "trend": trend,
        "categories": categories,
        "note": "GMV deferred until orders exist; values are demand/pipeline proxies from service_requests.",
    }
