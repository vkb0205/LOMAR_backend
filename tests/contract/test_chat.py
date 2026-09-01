"""Chat contract tests — T047, T046 decision recorded in research.md R9."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from tests.conftest import TEST_USER_B_ID, TEST_USER_ID, factory_token
from tests.fakes import FakeSupabase

THREAD_ID = "thread-1"
SERVICE_ID = "service-1"


def _store():
    return {
        "chat_threads": [{"id": THREAD_ID, "user_id": TEST_USER_ID, "context_type": "consultant"}],
        "chat_messages": [
            {"id": "m2", "thread_id": THREAD_ID, "user_id": TEST_USER_ID, "role": "assistant", "content": "second", "created_at": "2026-08-02T00:00:00+00:00"},
            {"id": "m1", "thread_id": THREAD_ID, "user_id": TEST_USER_ID, "role": "user", "content": "first", "created_at": "2026-08-01T00:00:00+00:00"},
        ],
        "services": [{"id": SERVICE_ID, "status": "active", "name": "Dress"}],
    }


def _install(app, failures=None):
    fake = FakeSupabase(rows=_store(), failures=failures or {})
    app.state.supabase_factory = lambda _token: fake
    return fake


def _auth(user_id=TEST_USER_ID):
    return {"Authorization": f"Bearer {factory_token(user_id)}"}


def _fake_ai(text="AI reply"):
    return MagicMock(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text=text)]))]
    )


def test_messages_are_owner_scoped_and_deterministically_ordered(client, app):
    _install(app)
    response = client.get(f"/api/v1/chat/threads/{THREAD_ID}/messages", headers=_auth())
    assert response.status_code == 200
    assert [message["id"] for message in response.json()["messages"]] == ["m1", "m2"]
    assert client.get(f"/api/v1/chat/threads/{THREAD_ID}/messages", headers=_auth(TEST_USER_B_ID)).status_code == 404


def test_thread_create_and_assistant_is_server_created(client, app):
    fake = _install(app)
    created = client.post("/api/v1/chat/threads", json={"contextType": "consultant"}, headers=_auth())
    assert created.status_code == 201
    thread_id = created.json()["threadId"]
    with patch("chatbot.runtime.generate_chat_reply", return_value="server text"):
        response = client.post(
            f"/api/v1/chat/threads/{thread_id}/messages",
            # A client attempting to dictate the assistant turn must not win:
            # `role` and `content` for the assistant are server-controlled.
            json={"content": "hello", "role": "assistant", "assistantMessage": {"content": "injected"}},
            headers=_auth(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["userMessage"]["role"] == "user"
        assert body["userMessage"]["content"] == "hello"
        assert body["assistantMessage"]["role"] == "assistant"
        assert body["assistantMessage"]["content"] == "server text"

    stored = [row for row in fake.rows["chat_messages"] if row["thread_id"] == thread_id]
    assert [row["role"] for row in stored] == ["user", "assistant"]
    assert all(row["user_id"] == TEST_USER_ID for row in stored)
    assert not any(row["content"] == "injected" for row in stored)


def test_empty_message_is_422(client, app):
    _install(app)
    assert (
        client.post(
            f"/api/v1/chat/threads/{THREAD_ID}/messages", json={"content": ""}, headers=_auth()
        ).status_code
        == 422
    )


def test_exchange_persists_user_and_server_assistant(client, app):
    fake = _install(app)
    with patch("chatbot.runtime.generate_chat_reply", return_value="AI reply"):
        response = client.post(
            f"/api/v1/chat/threads/{THREAD_ID}/messages", json={"content": "hello"}, headers=_auth()
        )
    assert response.status_code == 200
    body = response.json()
    assert body["userMessage"]["role"] == "user"
    assert body["assistantMessage"]["role"] == "assistant"
    assert body["persisted"] is True
    assert len([row for row in fake.rows["chat_messages"] if row["thread_id"] == THREAD_ID]) == 4


def test_suggested_service_passthrough(client, app):
    store = _store()
    store["chat_messages"].append(
        {"id": "m3", "thread_id": THREAD_ID, "user_id": TEST_USER_ID, "role": "assistant", "content": "service", "suggested_service_id": SERVICE_ID, "created_at": "2026-08-03T00:00:00+00:00"}
    )
    fake = FakeSupabase(rows=store)
    app.state.supabase_factory = lambda _token: fake
    response = client.get(f"/api/v1/chat/threads/{THREAD_ID}/suggested-service", headers=_auth())
    assert response.status_code == 200
    assert response.json()["service"]["id"] == SERVICE_ID


def test_persistence_failure_is_sanitized_503(client, app):
    _install(app, failures={"chat_messages": httpx.ConnectError("private db detail")})
    with patch("chatbot.runtime.generate_chat_reply", return_value="AI reply"):
        response = client.post(
            f"/api/v1/chat/threads/{THREAD_ID}/messages", json={"content": "hello"}, headers=_auth()
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "private db detail" not in response.text


def test_consult_is_public_and_returns_session(client, app):
    _install(app)
    with patch(
        "chatbot.runtime.run_consultant_agent",
        new=AsyncMock(return_value=("xin chào", [], [])),
    ):
        response = client.post("/api/v1/chat/consult", json={"message": "chào bạn"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "xin chào"
    assert body["sessionId"]
    assert body.get("degraded") is False


def test_consult_returns_service_cards(client, app):
    _install(app)
    services = [
        {
            "id": "svc-1",
            "name": "Gói chụp ảnh",
            "category": "photo",
            "base_price": 5_000_000,
            "currency": "VND",
            "thumbnail_url": "https://example.test/t.jpg",
            "vendor_id": "ven-1",
        }
    ]
    with patch(
        "chatbot.runtime.run_consultant_agent",
        new=AsyncMock(return_value=("Đây là gợi ý", ["search_services"], services)),
    ):
        response = client.post("/api/v1/chat/consult", json={"message": "tìm studio"})
    assert response.status_code == 200
    body = response.json()
    assert body["toolsUsed"] == ["search_services"]
    assert body["retrievedServices"] == [
        {
            "id": "svc-1",
            "name": "Gói chụp ảnh",
            "category": "photo",
            "basePrice": 5_000_000,
            "currency": "VND",
            "thumbnailUrl": "https://example.test/t.jpg",
            "vendorId": "ven-1",
        }
    ]


def test_consult_returns_wedding_plan_cards(client, app):
    """Plan cards flow through the same retrievedServices shape as services."""
    _install(app)
    plans = [
        {
            "id": "plan-1",
            "name": "Gói Cổ Điển",
            "category": "Cổ Điển",
            "base_price": 50_000_000,
            "currency": "VND",
            "thumbnail_url": "https://example.test/plan.jpg",
        }
    ]
    with patch(
        "chatbot.runtime.run_consultant_agent",
        new=AsyncMock(return_value=("Đây là gói phù hợp", ["list_wedding_plans"], plans)),
    ):
        response = client.post(
            "/api/v1/chat/consult", json={"message": "gói cưới tầm 80 triệu"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["toolsUsed"] == ["list_wedding_plans"]
    assert body["retrievedServices"] == [
        {
            "id": "plan-1",
            "name": "Gói Cổ Điển",
            "category": "Cổ Điển",
            "basePrice": 50_000_000,
            "currency": "VND",
            "thumbnailUrl": "https://example.test/plan.jpg",
            "vendorId": None,
        }
    ]


def test_consult_empty_reply_is_degraded_fallback(client, app):
    _install(app)
    with patch(
        "chatbot.runtime.run_consultant_agent",
        new=AsyncMock(return_value=("", [], [])),
    ):
        response = client.post("/api/v1/chat/consult", json={"message": "???"})
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["reply"]
    assert "Khám phá" in body["reply"] or "mình" in body["reply"].lower()
