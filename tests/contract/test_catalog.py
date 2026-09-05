"""Catalog contract tests — T020, written before catalog implementation."""

from __future__ import annotations

import httpx

from tests.fakes import FakeSupabase


VENDOR_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SERVICE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _catalog_store() -> dict[str, list[dict]]:
    return {
        "vendors": [
            {
                "id": VENDOR_ID,
                "name": "Lantern Studio",
                "category": "Chụp Ảnh",
                "rating_avg": 4.7,
                "address": "District 1",
                "image_url": "https://img/vendor.jpg",
                "status": "active",
            },
            {"id": "hidden-vendor", "name": "Hidden", "status": "suspended"},
        ],
        "services": [
            {
                "id": SERVICE_ID,
                "vendor_id": VENDOR_ID,
                "name": "Wedding photo",
                "category": "Chụp Ảnh",
                "status": "active",
                "thumbnail_url": "https://img/service.jpg",
            },
            {"id": "draft-service", "vendor_id": VENDOR_ID, "status": "draft"},
        ],
    }


def _set_store(app, store):
    app.state.supabase_factory = lambda _token: FakeSupabase(rows=store)


def test_anonymous_vendor_catalog_shape(client, app):
    _set_store(app, _catalog_store())
    response = client.get("/api/v1/catalog/vendors")
    assert response.status_code == 200
    assert response.json() == {
        "vendors": [
            {
                "id": VENDOR_ID,
                "name": "Lantern Studio",
                "category": "Chụp Ảnh",
                "rating": 4.7,
                "addr": "District 1",
                "img": "https://img/vendor.jpg",
            }
        ]
    }


def test_vendor_detail_and_customization_filter_hidden_rows(client, app):
    _set_store(app, _catalog_store())
    detail = client.get(f"/api/v1/catalog/vendors/{VENDOR_ID}")
    assert detail.status_code == 200
    assert detail.json()["vendor"]["id"] == VENDOR_ID
    assert [row["id"] for row in detail.json()["services"]] == [SERVICE_ID]

    customize = client.get("/api/v1/catalog/customize")
    assert customize.status_code == 200
    assert [row["id"] for row in customize.json()["services"]] == [SERVICE_ID]
    assert customize.json()["vendors"][0]["id"] == VENDOR_ID
    assert "serviceImages" not in customize.json()


def test_unknown_vendor_and_service_are_not_found(client, app):
    _set_store(app, _catalog_store())
    assert client.get("/api/v1/catalog/vendors/missing").status_code == 404
    assert client.get("/api/v1/catalog/services/missing/suggestion").status_code == 404
    assert client.get("/api/v1/catalog/services/draft-service/suggestion").status_code == 404


def test_catalog_database_failure_maps_to_503(client, app):
    fake = FakeSupabase(rows=_catalog_store(), failures={"vendors": httpx.ConnectError("secret db text")})
    app.state.supabase_factory = lambda _token: fake
    response = client.get("/api/v1/catalog/vendors")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "secret db text" not in response.text


# --- Wedding plans -------------------------------------------------------------

PLAN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
PLAN_ITEM_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
PLAN_SERVICE_ID = SERVICE_ID
PLAN_VENDOR_ID = VENDOR_ID


def _plan_store() -> dict[str, list[dict]]:
    return {
        "vendors": [
            {
                "id": PLAN_VENDOR_ID,
                "name": "Lantern Studio",
                "status": "active",
            }
        ],
        "services": [
            {
                "id": PLAN_SERVICE_ID,
                "vendor_id": PLAN_VENDOR_ID,
                "name": "Sảnh cưới",
                "category": "venue",
                "status": "active",
            }
        ],
        "wedding_plans": [
            {
                "id": PLAN_ID,
                "name": "Gói Trọn Gói Cổ Điển",
                "style": "Cổ Điển",
                "min_guests": 100,
                "max_guests": 180,
                "min_budget": 50000000,
                "max_budget": 80000000,
                "currency": "VND",
                "cover_image_url": "https://img/plan.jpg",
                "status": "active",
            },
            {"id": "draft-plan", "name": "Gói Ẩn", "min_budget": 100, "status": "draft"},
        ],
        "wedding_plan_items": [
            {
                "id": PLAN_ITEM_ID,
                "wedding_plan_id": PLAN_ID,
                "service_id": PLAN_SERVICE_ID,
                "role": "địa điểm",
                "sort_order": 0,
                "quantity": 1,
                "unit_price": 20000000,
                "currency": "VND",
                "services": {"id": PLAN_SERVICE_ID, "name": "Sảnh cưới", "category": "venue", "vendor_id": PLAN_VENDOR_ID},
            }
        ],
    }


def test_wedding_plans_list_is_public_and_active_only(client, app):
    _set_store(app, _plan_store())
    response = client.get("/api/v1/catalog/wedding-plans")
    assert response.status_code == 200
    body = response.json()
    assert [p["id"] for p in body["plans"]] == [PLAN_ID]  # draft hidden
    plan = body["plans"][0]
    assert plan["name"] == "Gói Trọn Gói Cổ Điển"
    assert plan["minBudget"] == 50000000
    assert plan["currency"] == "VND"


def test_wedding_plan_detail_returns_items(client, app):
    _set_store(app, _plan_store())
    response = client.get(f"/api/v1/catalog/wedding-plans/{PLAN_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["id"] == PLAN_ID
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["role"] == "địa điểm"
    assert item["service"]["id"] == PLAN_SERVICE_ID
    assert item["service"]["vendorId"] == PLAN_VENDOR_ID


def test_wedding_plan_unknown_or_inactive_is_404(client, app):
    _set_store(app, _plan_store())
    assert client.get("/api/v1/catalog/wedding-plans/missing").status_code == 404
    assert client.get("/api/v1/catalog/wedding-plans/draft-plan").status_code == 404
    # Draft plans must not appear in the detail join either.
    assert client.get("/api/v1/catalog/wedding-plans/draft-plan").status_code == 404
