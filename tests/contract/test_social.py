"""Social/blog contract tests — T037 (feed, ownership masking, idempotency)."""

from __future__ import annotations

from tests.conftest import TEST_USER_B_ID, TEST_USER_ID, factory_token
from tests.fakes import FakeSupabase

POST_ID = "post-1"
TAG_ID = "tag-1"


def _store() -> dict[str, list[dict]]:
    return {
        "posts": [
            {
                "id": POST_ID,
                "user_id": TEST_USER_ID,
                "content": "Hello world",
                "status": "published",
                "created_at": "2026-08-01T00:00:00+00:00",
            }
        ],
        "profiles": [
            {"id": TEST_USER_ID, "username": "alice", "avatar_url": None, "role": "customer"},
            {"id": TEST_USER_B_ID, "username": "bob", "avatar_url": None, "role": "customer"},
        ],
        "post_likes": [],
        "post_comments": [],
        "post_tags": [{"post_id": POST_ID, "tag_id": TAG_ID}],
        "tags": [{"id": TAG_ID, "name": "wedding"}],
        "follows": [],
        "vendors": [{"id": "vendor-1"}],
    }


def _install(app, store=None) -> FakeSupabase:
    fake = FakeSupabase(rows=store if store is not None else _store())
    app.state.supabase_factory = lambda _token: fake
    return fake


def _auth(user_id: str = TEST_USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {factory_token(user_id)}"}


def test_anonymous_feed_includes_author_tags_comments(client, app):
    _install(app)
    response = client.get("/api/v1/posts")
    assert response.status_code == 200
    post = response.json()["posts"][0]
    assert post["name"] == "alice"
    assert post["tags"] == "#wedding"
    assert post["likedByMe"] is False


def test_authenticated_create_like_comment(client, app):
    _install(app)
    created = client.post("/api/v1/posts", json={"content": "New post"}, headers=_auth())
    assert created.status_code == 201
    new_post_id = created.json()["id"]

    liked = client.post(f"/api/v1/posts/{new_post_id}/likes", headers=_auth(TEST_USER_B_ID))
    assert liked.status_code == 200
    assert liked.json() == {"liked": True, "likeCount": 1}

    commented = client.post(
        f"/api/v1/posts/{new_post_id}/comments",
        json={"content": "Nice!"},
        headers=_auth(TEST_USER_B_ID),
    )
    assert commented.status_code == 201


def test_like_unlike_and_follow_unfollow_are_idempotent(client, app):
    _install(app)
    for _ in range(2):
        assert client.post(f"/api/v1/posts/{POST_ID}/likes", headers=_auth()).status_code == 200
    unliked = client.delete(f"/api/v1/posts/{POST_ID}/likes", headers=_auth())
    assert unliked.json()["likeCount"] == 0
    again = client.delete(f"/api/v1/posts/{POST_ID}/likes", headers=_auth())
    assert again.status_code == 200

    for _ in range(2):
        followed = client.post(
            "/api/v1/follows",
            json={"followeeType": "user", "followeeId": TEST_USER_B_ID},
            headers=_auth(),
        )
        assert followed.status_code == 200
    unfollowed = client.delete(f"/api/v1/follows/user/{TEST_USER_B_ID}", headers=_auth())
    assert unfollowed.json()["following"] is False


def test_non_owner_edit_or_delete_is_masked_404(client, app):
    _install(app)
    edit = client.put(
        f"/api/v1/posts/{POST_ID}", json={"content": "hijacked"}, headers=_auth(TEST_USER_B_ID)
    )
    assert edit.status_code == 404
    delete = client.delete(f"/api/v1/posts/{POST_ID}", headers=_auth(TEST_USER_B_ID))
    assert delete.status_code == 404


def test_empty_content_and_unknown_tag_are_422(client, app):
    _install(app)
    assert client.post("/api/v1/posts", json={"content": ""}, headers=_auth()).status_code == 422
    assert (
        client.post(
            "/api/v1/posts", json={"content": "hi", "tagIds": ["missing"]}, headers=_auth()
        ).status_code
        == 422
    )
