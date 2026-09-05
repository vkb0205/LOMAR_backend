"""Dashboard contract tests — T029 (owner scoping, SC-004, R8 idempotency)."""

from __future__ import annotations

import httpx

from tests.conftest import TEST_USER_B_ID, TEST_USER_ID, factory_token
from tests.fakes import FakeSupabase

TASK_ID = "10000000-0000-0000-0000-000000000001"
VOUCHER_ID = "20000000-0000-0000-0000-000000000002"


def _store() -> dict[str, list[dict]]:
    return {
        "profiles": [
            {"id": TEST_USER_ID, "role": "customer"},
            {"id": TEST_USER_B_ID, "role": "customer"},
        ],
        "journey_tasks": [
            {"id": TASK_ID, "name": "Chốt ngân sách", "is_mandatory": True, "active": True}
        ],
        "user_journey_tasks": [
            {"user_id": TEST_USER_ID, "task_id": TASK_ID, "status": "completed"},
            {"user_id": TEST_USER_B_ID, "task_id": TASK_ID, "status": "pending"},
        ],
        "vouchers": [
            {
                "id": VOUCHER_ID,
                "title": "Giảm 10%",
                "discount_value": 10,
                "required_task_id": TASK_ID,
                "active": True,
            }
        ],
        "user_vouchers": [
            {"user_id": TEST_USER_B_ID, "voucher_id": VOUCHER_ID, "status": "unlocked"}
        ],
    }


def _install(app, store=None, failures=None) -> FakeSupabase:
    fake = FakeSupabase(rows=store if store is not None else _store(), failures=failures or {})
    app.state.supabase_factory = lambda _token: fake
    return fake


def _auth(user_id: str = TEST_USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory_token(user_id)}"}


def test_dashboard_returns_only_callers_rows(client, app):
    _install(app)
    response = client.get("/api/v1/me/dashboard", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    assert body["tasks"] == [
        {"taskId": TASK_ID, "name": "Chốt ngân sách", "isMandatory": True, "status": "completed"}
    ]
    assert body["vouchers"] == [
        {
            "voucherId": VOUCHER_ID,
            "title": "Giảm 10%",
            "discountValue": "10",
            "status": "locked",
            "requiredTaskId": TASK_ID,
        }
    ]
    assert [design["id"] for design in body["savedDesigns"]] == []


def test_user_b_cannot_see_user_a_rows(client, app):
    _install(app)
    body = client.get("/api/v1/me/dashboard", headers=_auth(TEST_USER_B_ID)).json()
    assert body["tasks"][0]["status"] == "pending"
    assert body["vouchers"][0]["status"] == "unlocked"
    assert [design["id"] for design in body["savedDesigns"]] == []


def test_anonymous_and_expired_tokens_are_401(client, app, expired_token):
    _install(app)
    assert client.get("/api/v1/me/dashboard").status_code == 401
    for path in (f"/api/v1/me/journey-tasks/{TASK_ID}", f"/api/v1/me/vouchers/{VOUCHER_ID}"):
        assert client.put(path, json={"status": "completed"}).status_code == 401
        assert (
            client.put(
                path,
                json={"status": "completed"},
                headers={"Authorization": f"Bearer {expired_token}"},
            ).status_code
            == 401
        )


def test_invalid_status_is_422(client, app):
    _install(app)
    assert (
        client.put(
            f"/api/v1/me/journey-tasks/{TASK_ID}", json={"status": "nope"}, headers=_auth()
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/v1/me/vouchers/{VOUCHER_ID}", json={"status": "redeemed"}, headers=_auth()
        ).status_code
        == 422
    )


def test_unknown_ids_are_404(client, app):
    _install(app)
    assert (
        client.put(
            "/api/v1/me/journey-tasks/missing", json={"status": "completed"}, headers=_auth()
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/api/v1/me/vouchers/missing", json={"status": "unlocked"}, headers=_auth()
        ).status_code
        == 404
    )


def test_repeated_upserts_do_not_duplicate_rows(client, app):
    fake = _install(app)
    for _ in range(3):
        assert (
            client.put(
                f"/api/v1/me/journey-tasks/{TASK_ID}",
                json={"status": "completed"},
                headers=_auth(),
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/v1/me/vouchers/{VOUCHER_ID}",
                json={"status": "unlocked"},
                headers=_auth(),
            ).status_code
            == 200
        )

    task_rows = [r for r in fake.rows["user_journey_tasks"] if r["user_id"] == TEST_USER_ID]
    voucher_rows = [r for r in fake.rows["user_vouchers"] if r["user_id"] == TEST_USER_ID]
    assert len(task_rows) == 1
    assert len(voucher_rows) == 1
    assert task_rows[0]["completed_at"] is not None
    assert voucher_rows[0]["unlocked_at"] is not None


def test_reverting_completion_clears_completed_at(client, app):
    fake = _install(app)
    client.put(
        f"/api/v1/me/journey-tasks/{TASK_ID}", json={"status": "completed"}, headers=_auth()
    )
    client.put(f"/api/v1/me/journey-tasks/{TASK_ID}", json={"status": "pending"}, headers=_auth())
    row = next(r for r in fake.rows["user_journey_tasks"] if r["user_id"] == TEST_USER_ID)
    assert row["status"] == "pending"
    assert row["completed_at"] is None


def test_database_failure_maps_to_503(client, app):
    _install(app, failures={"journey_tasks": httpx.ConnectError("pg down")})
    response = client.get("/api/v1/me/dashboard", headers=_auth())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
