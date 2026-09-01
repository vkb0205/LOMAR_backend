"""Business Intelligence contract tests — auth + empty metrics shape."""

from __future__ import annotations

from tests.conftest import TEST_ADMIN_ID, TEST_USER_ID, factory_token
from tests.fakes import FakeSupabase

TEST_VENDOR_ADMIN_ID = "44444444-4444-4444-4444-444444444444"
TEST_VENDOR_ID = "55555555-5555-5555-5555-555555555555"


def _store():
    return {
        "profiles": [
            {"id": TEST_USER_ID, "role": "customer", "full_name": "Customer"},
            {"id": TEST_ADMIN_ID, "role": "admin", "full_name": "Admin"},
            {"id": TEST_VENDOR_ADMIN_ID, "role": "vendor_admin", "full_name": "Vendor"},
        ],
        "vendors": [
            {
                "id": TEST_VENDOR_ID,
                "owner_id": TEST_VENDOR_ADMIN_ID,
                "name": "Demo Vendor",
                "status": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "services": [],
        "service_requests": [],
        "bi_agent_definitions": [
            {
                "id": "sales-analyst",
                "name": "Sales Analyst",
                "detail": "Finds demand patterns",
                "enabled": True,
                "sort_order": 10,
            },
            {
                "id": "customer-insights",
                "name": "Customer Insights",
                "detail": "Segments customers",
                "enabled": True,
                "sort_order": 20,
            },
            {
                "id": "campaign-optimizer",
                "name": "Campaign Optimizer",
                "detail": "Monitors outreach",
                "enabled": True,
                "sort_order": 30,
            },
            {
                "id": "operations-monitor",
                "name": "Operations Monitor",
                "detail": "Surfaces risks",
                "enabled": True,
                "sort_order": 40,
            },
        ],
        "bi_agent_runs": [],
        "bi_activities": [],
        "bi_recommendations": [
            {
                "id": "respond-fast-to-leads",
                "vendor_id": None,
                "title": "Respond fast",
                "detail": "Reply quickly",
                "impact": "Protect conversion",
                "action_label": "Preview",
                "status": "open",
                "created_at": "2026-08-01T00:00:00+00:00",
            }
        ],
        "bi_reports": [],
    }


def _install(app):
    fake = FakeSupabase(rows=_store())
    app.state.supabase_factory = lambda _token: fake
    return fake


def _auth(user_id: str, role: str = "customer"):
    return {"Authorization": f"Bearer {factory_token(user_id, role=role)}"}


def test_bi_overview_rejects_anonymous(client, app):
    _install(app)
    assert client.get("/api/v1/business-intelligence/overview").status_code == 401


def test_bi_overview_rejects_customer(client, app):
    _install(app)
    response = client.get(
        "/api/v1/business-intelligence/overview",
        headers=_auth(TEST_USER_ID, role="customer"),
    )
    assert response.status_code == 403


def test_bi_overview_vendor_admin_empty_metrics(client, app):
    _install(app)
    response = client.get(
        "/api/v1/business-intelligence/overview",
        headers=_auth(TEST_VENDOR_ADMIN_ID, role="vendor_admin"),
    )
    assert response.status_code == 200
    body = response.json()
    assert "metrics" in body
    assert len(body["metrics"]) == 4
    labels = {m["label"] for m in body["metrics"]}
    assert "Yêu cầu (leads)" in labels
    assert "Giá trị pipeline" in labels
    # Zero / empty state — no fabricated GMV
    assert body["metrics"][0]["value"] in ("0", "0")
    assert all("$42" not in m["value"] for m in body["metrics"])
    assert "agents" in body and len(body["agents"]) >= 1
    assert isinstance(body["trend"], list)
    assert isinstance(body["categories"], list)
    assert isinstance(body["recommendations"], list)
    assert isinstance(body["reports"], list)


def test_bi_overview_admin_ok(client, app):
    _install(app)
    response = client.get(
        "/api/v1/business-intelligence/overview",
        headers=_auth(TEST_ADMIN_ID, role="admin"),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["metrics"]) == 4


def test_bi_run_agent_and_report(client, app):
    fake = _install(app)
    headers = _auth(TEST_VENDOR_ADMIN_ID, role="vendor_admin")
    run = client.post(
        "/api/v1/business-intelligence/agents/run",
        json={"agentId": "sales-analyst"},
        headers=headers,
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["agent"]["id"] == "sales-analyst"
    assert payload["agent"]["status"] == "completed"
    assert payload["activity"]["kind"] == "agent"
    assert fake.rows["bi_agent_runs"]
    assert fake.rows["bi_activities"]

    report = client.post(
        "/api/v1/business-intelligence/reports",
        json={"period": "Last 7 days"},
        headers=headers,
    )
    assert report.status_code == 200
    assert report.json()["report"]["status"] == "ready"
    assert "GMV deferred" in report.json()["report"]["summary"] or "leads" in report.json()[
        "report"
    ]["summary"].lower()


def test_bi_chat_grounded(client, app):
    _install(app)
    response = client.post(
        "/api/v1/business-intelligence/chat",
        json={"message": "How is my pipeline?"},
        headers=_auth(TEST_VENDOR_ADMIN_ID, role="vendor_admin"),
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "gmv" not in reply or "not gmv" in reply or "deferred" in reply or "demand" in reply
