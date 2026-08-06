"""Catalog contract tests — T020, written before catalog implementation."""

from __future__ import annotations

import httpx

from tests.conftest import TEST_USER_ID
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
        "service_images": [
            {"id": "image-1", "service_id": SERVICE_ID, "image_url": "https://img/1.jpg"}
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
