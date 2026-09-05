"""Stage 3 — centralized role-based authorization contract tests (T013).

Verifies the four-tier security model:

  /public/*     — no auth required
  /user/*       — authenticated + role=customer
  /business/*   — authenticated + role=vendor
  /admin/*      — authenticated + role=admin

Security flow per request:
  request → AuthMiddleware (JWT verify) → require_user (DB role lookup)
  → role gate (403) → endpoint

The JWT ``role`` claim is never consulted — authorization is driven entirely by
``profiles.role`` resolved from the database (R6). These tests prove that
by issuing tokens whose ``role`` claim disagrees with the DB value.
"""

from __future__ import annotations

from tests.conftest import (
    TEST_ADMIN_ID,
    TEST_BUSINESS_ID,
    TEST_USER_ID,
    factory_token,
)
from tests.fakes import FakeSupabase


def _store():
    return {
        "profiles": [
            {"id": TEST_USER_ID, "role": "customer", "full_name": "User"},
            {"id": TEST_BUSINESS_ID, "role": "vendor", "full_name": "Biz"},
            {"id": TEST_ADMIN_ID, "role": "admin", "full_name": "Admin"},
        ],
        "journey_tasks": [],
        "user_journey_tasks": [],
        "vouchers": [],
        "user_vouchers": [],
        "services": [{"id": "service-1", "vendor_id": "vendor-business", "name": "Photo", "status": "active"}],
        "service_requests": [],
        "vendors": [{"id": "vendor-business", "owner_id": TEST_BUSINESS_ID, "status": "active"}],
        "posts": [],
        "post_comments": [],
    }


def _install(app):
    """Wire a FakeSupabase into both caller-JWT and service-role factories."""
    fake = FakeSupabase(rows=_store())
    app.state.supabase_factory = lambda _token: fake
    app.state.supabase_admin_factory = lambda: fake
    return fake


def _auth(user_id, role="user"):
    """Build an ``Authorization`` header with a signed JWT.

    The ``role`` here is the *JWT claim* — it is intentionally misleading in
    some tests to prove the server ignores it.
    """
    return {"Authorization": f"Bearer {factory_token(user_id, role=role)}"}


# ---------------------------------------------------------------------------
# 1. Unauthenticated request → 401
# ---------------------------------------------------------------------------


class TestUnauthenticated:
    def test_admin_route_no_token_returns_401(self, client, app):
        _install(app)
        resp = client.get("/api/v1/admin/metrics")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

    def test_business_route_no_token_returns_401(self, client, app):
        _install(app)
        resp = client.get("/api/v1/business/services")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"

    def test_user_route_no_token_returns_401(self, client, app):
        _install(app)
        resp = client.get("/api/v1/me/dashboard")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthenticated"


# ---------------------------------------------------------------------------
# 2. user accessing /user → allowed
# ---------------------------------------------------------------------------


class TestUserAccess:
    def test_user_read_dashboard_allowed(self, client, app):
        _install(app)
        resp = client.get("/api/v1/me/dashboard", headers=_auth(TEST_USER_ID))
        assert resp.status_code == 200

    def test_user_create_chat_thread_allowed(self, client, app):
        _install(app)
        resp = client.post(
            "/api/v1/chat/threads",
            json={"contextType": "consultant"},
            headers=_auth(TEST_USER_ID),
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# 3. user accessing /business → 403
# ---------------------------------------------------------------------------


class TestUserDeniedBusiness:
    def test_user_accesses_business_returns_403(self, client, app):
        _install(app)
        resp = client.get("/api/v1/business/services", headers=_auth(TEST_USER_ID))
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# 4. user accessing /admin → 403
# ---------------------------------------------------------------------------


class TestUserDeniedAdmin:
    def test_user_accesses_admin_returns_403(self, client, app):
        _install(app)
        resp = client.get("/api/v1/admin/metrics", headers=_auth(TEST_USER_ID))
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# 5. business accessing /business → allowed
# ---------------------------------------------------------------------------


class TestBusinessAccess:
    def test_business_reads_services_allowed(self, client, app):
        _install(app)
        resp = client.get(
            "/api/v1/business/services",
            headers=_auth(TEST_BUSINESS_ID, role="vendor"),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["id"] == "service-1"

    def test_business_reads_service_requests_allowed(self, client, app):
        _install(app)
        resp = client.get(
            "/api/v1/business/service-requests",
            headers=_auth(TEST_BUSINESS_ID, role="vendor"),
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6. business accessing /admin → 403
# ---------------------------------------------------------------------------


class TestBusinessDeniedAdmin:
    def test_business_accesses_admin_returns_403(self, client, app):
        _install(app)
        resp = client.get(
            "/api/v1/admin/metrics",
            headers=_auth(TEST_BUSINESS_ID, role="vendor"),
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# 7. admin accessing /admin → allowed
# ---------------------------------------------------------------------------


class TestAdminAccess:
    def test_admin_reads_metrics_allowed(self, client, app):
        _install(app)
        resp = client.get(
            "/api/v1/admin/metrics",
            headers=_auth(TEST_ADMIN_ID, role="admin"),
        )
        assert resp.status_code == 200
        assert resp.json()["users"] == 3

    def test_admin_cannot_access_exact_business_routes(self, client, app):
        _install(app)
        resp = client.get(
            "/api/v1/business/services",
            headers=_auth(TEST_ADMIN_ID, role="admin"),
        )
        assert resp.status_code == 403

    def test_admin_cannot_access_exact_user_routes(self, client, app):
        _install(app)
        resp = client.get(
            "/api/v1/me/dashboard",
            headers=_auth(TEST_ADMIN_ID, role="admin"),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 8. public endpoint without JWT → allowed
# ---------------------------------------------------------------------------


class TestPublicEndpoints:
    def test_health_without_jwt_allowed(self, client, app):
        _install(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_catalog_without_jwt_allowed(self, client, app):
        _install(app)
        resp = client.get("/api/v1/catalog/vendors")
        assert resp.status_code == 200

    def test_analytics_tracking_without_jwt_allowed(self, client, app):
        _install(app)
        resp = client.post(
            "/api/v1/analytics/page-views",
            json={
                "id": "view-1",
                "sessionId": "s1",
                "visitorId": "v1",
                "pagePath": "/home",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_backend_does_not_proxy_sign_in(self, client, app):
        _install(app)
        assert client.post("/api/v1/auth/sign-in", json={}).status_code == 404


# ---------------------------------------------------------------------------
# R6: JWT role claim is never trusted — profiles.role is authoritative
# ---------------------------------------------------------------------------


class TestJwtRoleNotTrusted:
    def test_stale_jwt_admin_claim_but_db_user_is_403(self, client, app):
        """Token claims admin but profiles.role is customer, so access is denied."""
        _store_data = _store()
        _store_data["profiles"] = [
            {"id": TEST_USER_ID, "role": "customer"},
        ]
        fake = FakeSupabase(rows=_store_data)
        app.state.supabase_factory = lambda _token: fake
        app.state.supabase_admin_factory = lambda: fake

        resp = client.get(
            "/api/v1/admin/metrics",
            headers=_auth(TEST_USER_ID, role="admin"),
        )
        assert resp.status_code == 403

    def test_stale_jwt_user_claim_but_db_admin_is_allowed(self, client, app):
        """Token claims user but profiles.role is admin, so access is allowed."""
        _store_data = _store()
        _store_data["profiles"] = [
            {"id": TEST_USER_ID, "role": "admin"},
        ]
        fake = FakeSupabase(rows=_store_data)
        app.state.supabase_factory = lambda _token: fake
        app.state.supabase_admin_factory = lambda: fake

        resp = client.get(
            "/api/v1/admin/metrics",
            headers=_auth(TEST_USER_ID, role="user"),
        )
        assert resp.status_code == 200

    def test_stale_jwt_customer_claim_but_db_vendor_is_allowed(self, client, app):
        """Token claims customer but profiles.role is vendor, so vendor access is allowed."""
        _store_data = _store()
        _store_data["profiles"] = [
            {"id": TEST_USER_ID, "role": "vendor"},
        ]
        fake = FakeSupabase(rows=_store_data)
        app.state.supabase_factory = lambda _token: fake

        resp = client.get(
            "/api/v1/business/services",
            headers=_auth(TEST_USER_ID, role="customer"),
        )
        assert resp.status_code == 200
