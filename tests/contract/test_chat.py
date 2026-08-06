"""Chat contract tests — T047, T046 decision recorded in research.md R9."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    with patch("google.genai.Client") as genai_client:
        genai_client.return_value.models.generate_content.return_value = _fake_ai("server text")
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
    with patch("google.genai.Client") as genai_client:
        genai_client.return_value.models.generate_content.return_value = _fake_ai()
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
    with patch("google.genai.Client") as genai_client:
        genai_client.return_value.models.generate_content.return_value = _fake_ai()
        response = client.post(
            f"/api/v1/chat/threads/{THREAD_ID}/messages", json={"content": "hello"}, headers=_auth()
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "private db detail" not in response.text
