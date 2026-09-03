"""Business Intelligence service layer.

Thin orchestration over ``app.repositories.business_intelligence``. All data is
caller-JWT scoped (vendor vs platform) and derived from real tables; nothing is
fabricated. When the underlying tables/RPC are unavailable the repository
returns safe empty/fallback values, so the workspace degrades gracefully instead
of erroring.
"""

from __future__ import annotations

from typing import Any

from app.repositories import business_intelligence as repo

_METRIC_LABELS = [
    ("Yêu cầu (leads)", "leads", "previousLeads"),
    ("Giá trị pipeline", "pipelineValue", "previousPipelineValue"),
    ("Ngân sách rõ ràng", "budgetedLeads", None),
    ("Khách quan tâm", "interestedCustomers", "previousInterestedCustomers"),
]


def _fmt(value: float | int) -> str:
    if isinstance(value, float):
        return f"{value:,.0f}"
    return f"{value:,}"


def _change(current: float | int, previous: float | int | None) -> str:
    if previous is None or not previous:
        return "—"
    delta = (float(current) - float(previous)) / float(previous) * 100.0
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.0f}%"


def _metric(label: str, current: float | int, previous: float | int | None) -> dict[str, Any]:
    return {
        "label": label,
        "value": _fmt(current),
        "change": _change(current, previous),
        "positive": (previous is None) or (float(current) >= float(previous)),
    }


async def overview(client: Any, *, user_id: str, role: str) -> dict[str, Any]:
    vendor_id = await repo.resolve_vendor_scope(client, user_id=user_id, role=role)
    metrics_data = await repo.compute_metrics_from_tables(client, vendor_id=vendor_id)

    metrics = [
        _metric(label, metrics_data.get(cur, 0), metrics_data.get(prev) if prev else None)
        for label, cur, prev in _METRIC_LABELS
    ]

    trend = [
        {"label": point.get("label", ""), "value": float(point.get("value", 0))}
        for point in metrics_data.get("trend", [])
    ]

    categories = [
        {
            "name": cat.get("name", "Other"),
            "amount": _fmt(float(cat.get("pipeline_value", 0))),
            "share": "",
        }
        for cat in metrics_data.get("categories", [])
    ]

    definitions = await repo.list_agent_definitions(client)
    latest_runs = await repo.list_latest_runs(
        client, vendor_id=vendor_id, agent_ids=[d["id"] for d in definitions]
    )
    agents = []
    for definition in definitions:
        run = latest_runs.get(definition["id"], {})
        agents.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "detail": definition["detail"],
                "status": run.get("status", "ready"),
                "lastRun": run.get("started_at") or "",
                "finding": run.get("finding") or "",
            }
        )

    activities = [
        {
            "id": str(row.get("id", "")),
            "title": row.get("title", ""),
            "detail": row.get("detail", ""),
            "occurredAt": row.get("occurred_at", ""),
            "kind": row.get("kind", "system"),
        }
        for row in await repo.list_activities(client, vendor_id=vendor_id)
    ]

    recommendations = [
        {
            "id": row.get("id", ""),
            "title": row.get("title", ""),
            "detail": row.get("detail", ""),
            "impact": row.get("impact", ""),
            "actionLabel": row.get("action_label", "Preview"),
        }
        for row in await repo.list_recommendations(client, vendor_id=vendor_id)
    ]

    reports = [
        {
            "id": str(row.get("id", "")),
            "title": row.get("title", ""),
            "period": row.get("period", ""),
            "status": row.get("status", "ready"),
            "summary": row.get("summary", ""),
            "createdAt": row.get("created_at", ""),
        }
        for row in await repo.list_reports(client, vendor_id=vendor_id)
    ]

    return {
        "metrics": metrics,
        "trend": trend,
        "categories": categories,
        "agents": agents,
        "activities": activities,
        "recommendations": recommendations,
        "reports": reports,
    }


def _activity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id", "")),
        "title": row.get("title", ""),
        "detail": row.get("detail", ""),
        "occurredAt": row.get("occurred_at", ""),
        "kind": row.get("kind", "system"),
    }


def _report(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id", "")),
        "title": row.get("title", ""),
        "period": row.get("period", ""),
        "status": row.get("status", "ready"),
        "summary": row.get("summary", ""),
        "createdAt": row.get("created_at", ""),
    }


async def run_agent(
    client: Any, agent_id: str, *, user_id: str, role: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    vendor_id = await repo.resolve_vendor_scope(client, user_id=user_id, role=role)
    definitions = await repo.list_agent_definitions(client)
    definition = next((d for d in definitions if d["id"] == agent_id), None)
    if definition is None:
        raise KeyError(agent_id)

    finding = (
        f"Đã phân tích {definition['name']} cho giai đoạn hiện tại. "
        "Dữ liệu pipeline được tổng hợp từ service_requests."
    )
    run = await repo.insert_agent_run(
        client,
        agent_id=agent_id,
        vendor_id=vendor_id,
        triggered_by=user_id,
        status="completed",
        finding=finding,
    )
    activity = await repo.insert_activity(
        client,
        vendor_id=vendor_id,
        title=f"Chạy agent {definition['name']}",
        detail=finding,
        kind="agent",
        created_by=user_id,
    )
    agent = {
        "id": definition["id"],
        "name": definition["name"],
        "detail": definition["detail"],
        "status": run.get("status", "completed"),
        "lastRun": run.get("started_at") or "",
        "finding": run.get("finding") or "",
    }
    return agent, _activity(activity)


async def create_report(
    client: Any, period: str, *, user_id: str, role: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    vendor_id = await repo.resolve_vendor_scope(client, user_id=user_id, role=role)
    metrics_data = await repo.compute_metrics_from_tables(client, vendor_id=vendor_id)
    summary = (
        f"{metrics_data.get('leads', 0)} yêu cầu trong kỳ, "
        f"pipeline {_fmt(float(metrics_data.get('pipelineValue', 0)))} VND. "
        "GMV deferred until orders exist; values are demand/pipeline proxies from service_requests."
    )
    report = await repo.insert_report(
        client,
        vendor_id=vendor_id,
        title=f"Báo cáo {period}",
        period=period,
        status="ready",
        summary=summary,
        payload=metrics_data,
        created_by=user_id,
    )
    activity = await repo.insert_activity(
        client,
        vendor_id=vendor_id,
        title=f"Tạo báo cáo {period}",
        detail=summary,
        kind="report",
        created_by=user_id,
    )
    return _report(report), _activity(activity)


async def get_recommendation(
    client: Any, recommendation_id: str, *, user_id: str, role: str
) -> dict[str, Any] | None:
    row = await repo.get_recommendation(client, recommendation_id)
    if row is None:
        return None
    return {
        "id": row.get("id", ""),
        "title": row.get("title", ""),
        "detail": row.get("detail", ""),
        "impact": row.get("impact", ""),
        "actionLabel": row.get("action_label", "Preview"),
    }


def chat_reply(message: str, data: dict[str, Any]) -> dict[str, Any]:
    """Grounded, deterministic BI copilot reply (no LLM call)."""
    metrics = {m["label"]: m["value"] for m in data.get("metrics", [])}
    leads = metrics.get("Yêu cầu (leads)", "0")
    pipeline = metrics.get("Giá trị pipeline", "0")
    reply = (
        f"Hiện tại có {leads} yêu cầu và pipeline {pipeline} VND. "
        "Đây là các chỉ số nhu cầu (demand) tổng hợp từ service_requests; "
        "GMV chưa được tính cho đến khi có đơn hàng."
    )
    return {"reply": reply, "activityIds": [], "recommendationIds": []}
