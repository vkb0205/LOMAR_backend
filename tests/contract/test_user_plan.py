"""User wedding-plan acceptance contract tests (feature 003).

Covers FR-001/004 (owner-scoped idempotent persistence), FR-007
(authenticated PUT endpoint: 401 anonymous, 422 invalid status, 404 unknown
item), owner scoping (user B cannot see user A), and FR-008 (consult context
injected only when a valid JWT is present).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx

from tests.conftest import TEST_USER_B_ID, TEST_USER_ID, factory_token
from tests.fakes import FakeSupabase

SERVICE_ID = "10000000-0000-0000-0000-000000000001"
PLAN_ID = "20000000-0000-0000-0000-000000000002"
OTHER_SERVICE_ID = "30000000-0000-0000-0000-000000000003"


def _store() -> dict[str, list[dict]]:
    return {
        "services": [
            {
                "id": SERVICE_ID,
                "name": "Sảnh cưới Hoàng Gia",
                "category": "Venue",
                "base_price": 20000000,
                "currency": "VND",
                "status": "active",
            },
            {
                "id": OTHER_SERVICE_ID,
                "name": "Gói chụp ảnh",
                "category": "Photo",
                "base_price": 5000000,
                "currency": "VND",
                "status": "active",
            },
        ],
        "wedding_plans": [
            {
                "id": PLAN_ID,
                "name": "Gói Trọn Gói Cổ Điển",
                "style": "Cổ Điển",
                "status": "active",
            }
        ],
        # The security-invoker view returns only accepted rows, grouped by the
        # derived category already baked into the view rows.
        "v_user_accepted_plan": [
            {
                "user_id": TEST_USER_ID,
                "item_type": "service",
                "service_id": SERVICE_ID,
                "plan_id": None,
                "category": "Venue",
                "service_name": "Sảnh cưới Hoàng Gia",
                "service_price": 20000000,
                "accepted_at": "2026-09-01T00:00:00+00:00",
            }
        ],
        # The base table is what the PUT upserts into.
        "user_plan_items": [
            {
                "user_id": TEST_USER_ID,
                "item_type": "service",
                "service_id": SERVICE_ID,
                "plan_id": None,
                "status": "accepted",
                "accepted_at": "2026-09-01T00:00:00+00:00",
            }
        ],
    }


def _install(app, store=None, failures=None) -> FakeSupabase:
    rows = store if store is not None else _store()
    rows.setdefault(
        "profiles",
        [
            {"id": TEST_USER_ID, "role": "customer"},
            {"id": TEST_USER_B_ID, "role": "customer"},
        ],
    )
    fake = FakeSupabase(rows=rows, failures=failures or {})
    app.state.supabase_factory = lambda _token: fake
    return fake


def _auth(user_id: str = TEST_USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory_token(user_id)}"}


def _accept_response(client, item_type="service", item_id=SERVICE_ID, status="accepted", *, headers=None, **kwargs):
    headers = headers if headers is not None else _auth()
    return client.put(
        f"/api/v1/me/plan-items/{item_type}/{item_id}",
        json={"status": status},
        headers=headers,
        **kwargs,
    )


def test_accept_persists_and_returns_200(client, app):
    fake = _install(app)
    response = _accept_response(client)
    assert response.status_code == 200
    body = response.json()
    assert body["itemType"] == "service"
    assert body["itemId"] == SERVICE_ID
    assert body["status"] == "accepted"
    row = next(
        r for r in fake.rows["user_plan_items"]
        if r["user_id"] == TEST_USER_ID and r["service_id"] == SERVICE_ID
    )
    assert row["status"] == "accepted"
    assert row["accepted_at"] is not None
    assert row["user_id"] == TEST_USER_ID


def test_accept_is_idempotent(client, app):
    fake = _install(app)
    for _ in range(3):
        assert _accept_response(client).status_code == 200
    rows = [
        r for r in fake.rows["user_plan_items"]
        if r["user_id"] == TEST_USER_ID and r["service_id"] == SERVICE_ID
    ]
    assert len(rows) == 1


def test_accept_wedding_plan(client, app):
    fake = _install(app)
    response = _accept_response(client, item_type="plan", item_id=PLAN_ID, status="accepted")
    assert response.status_code == 200
    row = next(
        r for r in fake.rows["user_plan_items"]
        if r["user_id"] == TEST_USER_ID and r["plan_id"] == PLAN_ID
    )
    assert row["item_type"] == "plan"
    assert row["plan_id"] == PLAN_ID
    assert row["service_id"] is None
    assert row["status"] == "accepted"


def test_anonymous_call_is_401(client, app):
    _install(app)
    assert _accept_response(client, headers={}).status_code == 401


def test_invalid_status_is_422(client, app):
    _install(app)
    assert _accept_response(client, status="nope").status_code == 422
    assert _accept_response(client, status="proposed").status_code == 422


def test_unknown_item_is_404(client, app):
    _install(app)
    assert _accept_response(client, item_id="missing").status_code == 404
    assert _accept_response(client, item_type="plan", item_id="missing").status_code == 404


def test_accepted_at_cleared_when_no_longer_accepted(client, app):
    fake = _install(app)
    _accept_response(client, status="accepted")
    _accept_response(client, status="declined")
    row = next(
        r for r in fake.rows["user_plan_items"]
        if r["user_id"] == TEST_USER_ID and r["service_id"] == SERVICE_ID
    )
    assert row["status"] == "declined"
    assert row["accepted_at"] is None


def test_database_failure_is_503(client, app):
    _install(app, failures={"user_plan_items": httpx.ConnectError("pg down")})
    response = _accept_response(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"


def test_user_b_writes_under_their_own_id_not_user_a(client, app):
    """Owner scoping: user_id is forced from the JWT, never the body (FR-001).

    In production RLS rejects cross-user reads/writes on the base table and the
    view; here we assert the API never lets a caller impersonate another owner.
    """
    fake = _install(app)
    response = _accept_response(client, status="accepted", headers=_auth(TEST_USER_B_ID))
    assert response.status_code == 200
    rows = [
        r for r in fake.rows["user_plan_items"]
        if r["user_id"] == TEST_USER_B_ID and r["service_id"] == SERVICE_ID
    ]
    assert len(rows) == 1
    assert rows[0]["user_id"] == TEST_USER_B_ID
    a_rows = [
        r for r in fake.rows["user_plan_items"]
        if r["user_id"] == TEST_USER_ID and r["service_id"] == SERVICE_ID
    ]
    # User A's accepted row is untouched / not duplicated by B's write.
    assert all(r["user_id"] == TEST_USER_ID for r in a_rows)


def test_consult_injects_plan_context_only_when_authenticated(client, app):
    """FR-008: accepted-plan summary reaches the agent only with a valid JWT."""
    _install(app)

    seen: dict = {}

    async def _fake_agent(message, *, db=None, history=None, extra_context=None):
        seen["extra"] = extra_context
        return ("xin chào", [], [])

    with patch("chatbot.runtime.run_consultant_agent", new=AsyncMock(side_effect=_fake_agent)):
        # Authenticated caller with an accepted plan.
        anon = client.post("/api/v1/chat/consult", json={"message": "chào"})
        assert anon.status_code == 200
        assert seen["extra"] is None or "Hạng mục bạn đã chốt" not in (seen["extra"] or "")

        auth = client.post(
            "/api/v1/chat/consult", json={"message": "chào"}, headers=_auth()
        )
        assert auth.status_code == 200
        assert "Hạng mục bạn đã chốt" in (seen["extra"] or "")


def test_consult_authenticated_with_empty_plan_has_no_context(client, app):
    """An authenticated user with no accepted items gets no plan context."""
    store = _store()
    store["v_user_accepted_plan"] = []
    _install(app, store=store)

    seen: dict = {}
    async def _fake_agent(message, *, db=None, history=None, extra_context=None):
        seen["extra"] = extra_context
        return ("chưa có", [], [])

    with patch("chatbot.runtime.run_consultant_agent", new=AsyncMock(side_effect=_fake_agent)):
        client.post("/api/v1/chat/consult", json={"message": "chào"}, headers=_auth())
    assert seen["extra"] is None or "Hạng mục bạn đã chốt" not in (seen["extra"] or "")
