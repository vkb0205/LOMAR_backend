"""End-to-end checks for the public/customer/vendor/admin hierarchy."""

from tests.conftest import TEST_ADMIN_ID, TEST_USER_ID, TEST_VENDOR_USER_ID, factory_token
from tests.fakes import FakeSupabase


def _auth(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory_token(user_id)}"}


def _install(app):
    fake = FakeSupabase(rows={
        "profiles": [
            {"id": TEST_USER_ID, "role": "customer"},
            {"id": TEST_VENDOR_USER_ID, "role": "vendor"},
            {"id": TEST_ADMIN_ID, "role": "admin"},
        ],
        "vendors": [
            {"id": "vendor-a", "owner_id": TEST_VENDOR_USER_ID, "status": "active"},
            {"id": "vendor-b", "owner_id": "other-vendor", "status": "active"},
        ],
        "services": [
            {"id": "service-a", "vendor_id": "vendor-a", "status": "active", "created_at": "2026-01-01"},
            {"id": "service-b", "vendor_id": "vendor-b", "status": "active", "created_at": "2026-01-01"},
        ],
        "service_requests": [],
        "vouchers": [],
    })
    app.state.supabase_factory = lambda _token: fake
    app.state.supabase_admin_factory = lambda: fake
    return fake


def test_public_route_needs_no_jwt(client, app):
    _install(app)
    assert client.get("/api/v1/public/health").status_code == 200


def test_hierarchical_role_routes(client, app):
    _install(app)
    assert client.get("/api/v1/user/profile").status_code == 401
    assert client.get("/api/v1/user/profile", headers=_auth(TEST_USER_ID)).status_code == 200
    assert client.get("/api/v1/business/services", headers=_auth(TEST_USER_ID)).status_code == 403
    assert client.get("/api/v1/user/profile", headers=_auth(TEST_VENDOR_USER_ID)).status_code == 200
    assert client.get("/api/v1/user/profile", headers=_auth(TEST_ADMIN_ID)).status_code == 200
    assert client.get("/api/v1/business/services", headers=_auth(TEST_ADMIN_ID)).status_code == 200
    assert client.get("/api/v1/admin/metrics", headers=_auth(TEST_VENDOR_USER_ID)).status_code == 403
    assert client.get("/api/v1/admin/metrics", headers=_auth(TEST_ADMIN_ID)).status_code == 200


def test_vendor_lists_only_owned_resources(client, app):
    _install(app)
    response = client.get("/api/v1/business/services", headers=_auth(TEST_VENDOR_USER_ID))
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == ["service-a"]


def test_admin_lists_all_vendor_resources(client, app):
    _install(app)
    response = client.get("/api/v1/business/services", headers=_auth(TEST_ADMIN_ID))
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {"service-a", "service-b"}


def test_vendor_cannot_modify_another_vendor_resource(client, app):
    fake = _install(app)
    allowed = client.put(
        "/api/v1/business/services/service-a/status",
        json={"status": "archived"},
        headers=_auth(TEST_VENDOR_USER_ID),
    )
    denied = client.put(
        "/api/v1/business/services/service-b/status",
        json={"status": "archived"},
        headers=_auth(TEST_VENDOR_USER_ID),
    )
    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert next(row for row in fake.rows["services"] if row["id"] == "service-b")["status"] == "active"


def test_admin_can_modify_any_vendor_resource(client, app):
    fake = _install(app)
    response = client.put(
        "/api/v1/business/services/service-b/status",
        json={"status": "archived"},
        headers=_auth(TEST_ADMIN_ID),
    )
    assert response.status_code == 200
    assert next(row for row in fake.rows["services"] if row["id"] == "service-b")["status"] == "archived"


def test_jwt_role_claim_cannot_escalate(client, app):
    _install(app)
    forged_claim = {"Authorization": f"Bearer {factory_token(TEST_USER_ID, role='admin')}"}
    assert client.get("/api/v1/admin/metrics", headers=forged_claim).status_code == 403
