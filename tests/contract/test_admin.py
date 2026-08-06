"""Admin + analytics contract tests — T055/T056."""

from __future__ import annotations

from tests.conftest import TEST_ADMIN_ID, TEST_USER_ID, factory_token
from tests.fakes import FakeSupabase


def _store():
    return {
        "profiles": [
            {"id": TEST_USER_ID, "role": "customer", "full_name": "User"},
            {"id": TEST_ADMIN_ID, "role": "admin", "full_name": "Admin"},
        ],
        "vendors": [{"id": "vendor-1", "status": "draft"}],
        "services": [],
        "posts": [],
        "post_comments": [],
        "reviews": [],
        "service_requests": [],
        "ai_design_generations": [],
        "journey_tasks": [],
        "vouchers": [],
        "analytics_page_views": [],
    }


def _install(app, rpc_results=None):
    fake = FakeSupabase(
        rows=_store(),
        rpc_results=rpc_results
        or {
            "record_page_view": "view-1",
            "record_page_engagement": None,
            "get_admin_website_analytics": {
                "summary": {"views": 1, "uniqueVisitors": 1, "sessions": 1, "avgDurationSeconds": 4, "bounceRate": 0},
                "pages": [],
                "behaviours": [],
                "daily": [],
            },
        },
    )
    app.state.supabase_factory = lambda _token: fake
    # The admin route must use the service client dependency; in tests it is
    # the same deterministic store, never a live credential.
    app.state.supabase_admin_factory = lambda: fake
    return fake


def _auth(user_id):
    role = "admin" if user_id == TEST_ADMIN_ID else "customer"
    return {"Authorization": f"Bearer {factory_token(user_id, role=role)}"}


def test_every_admin_route_rejects_anonymous_and_non_admin(client, app):
    _install(app)
    for path in (
        "/api/v1/admin/metrics",
        "/api/v1/admin/profiles",
        "/api/v1/admin/vendors",
        "/api/v1/admin/services",
        "/api/v1/admin/posts",
        "/api/v1/admin/comments",
        "/api/v1/admin/reviews",
        "/api/v1/admin/journey-tasks",
        "/api/v1/admin/vouchers",
        "/api/v1/admin/service-requests",
        "/api/v1/admin/generations",
        "/api/v1/admin/analytics",
    ):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=_auth(TEST_USER_ID)).status_code == 403


def test_admin_reads_and_mutations_succeed(client, app):
    _install(app)
    metrics = client.get("/api/v1/admin/metrics", headers=_auth(TEST_ADMIN_ID))
    assert metrics.status_code == 200
    assert metrics.json()["vendorsPending"] == 1

    status_response = client.put(
        "/api/v1/admin/vendors/vendor-1/status",
        json={"status": "active"},
        headers=_auth(TEST_ADMIN_ID),
    )
    assert status_response.status_code == 200


def test_admin_validation_and_days_bounds(client, app):
    _install(app)
    assert client.get("/api/v1/admin/analytics?days=0", headers=_auth(TEST_ADMIN_ID)).status_code == 422
    assert client.get("/api/v1/admin/analytics?days=366", headers=_auth(TEST_ADMIN_ID)).status_code == 422
    assert (
        client.put(
            "/api/v1/admin/profiles/user-1/role",
            json={"role": "root"},
            headers=_auth(TEST_ADMIN_ID),
        ).status_code
        == 422
    )


def test_analytics_tracking_is_public_and_ignores_client_user_id(client, app):
    fake = _install(app)
    response = client.post(
        "/api/v1/analytics/page-views",
        json={
            "id": "view-1",
            "sessionId": "session-1",
            "visitorId": "visitor-1",
            "pagePath": "/home",
            "user_id": "impersonated",
        },
    )
    assert response.status_code == 200
    assert fake.rpc_calls[-1][0] == "record_page_view"
    assert "user_id" not in fake.rpc_calls[-1][1]

    engagement = client.post(
        "/api/v1/analytics/page-views/view-1/engagement",
        json={"sessionId": "session-1", "visitorId": "visitor-1", "durationSeconds": 2, "maxScrollPercent": 60},
    )
    assert engagement.status_code == 200


def test_admin_analytics_returns_rpc_payload(client, app):
    _install(app)
    response = client.get("/api/v1/admin/analytics?days=30", headers=_auth(TEST_ADMIN_ID))
    assert response.status_code == 200
    assert response.json()["summary"]["views"] == 1
