"""Social domain mapping and masked ownership rules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.errors import NotFoundError
from app.repositories import social as repository
from app.schemas.social import FeedPost

DEFAULT_BLOG_AVATAR = "https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&q=80&w=120"


def format_post_time(created_at: str | None) -> str:
    if not created_at:
        return "1 giờ"
    try:
        post_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if post_date.tzinfo is None:
            post_date = post_date.replace(tzinfo=timezone.utc)
    except ValueError:
        return "1 giờ"
    hours = max(0, int((datetime.now(timezone.utc) - post_date).total_seconds() // 3600))
    return f"{hours or 1} giờ" if hours < 24 else f"{hours // 24} ngày"


async def build_feed(client: Any, user_id: str = "") -> list[FeedPost]:
    posts = await repository.list_visible_posts(client)
    post_ids = [row["id"] for row in posts]
    profiles = await repository.profiles_by_ids(client, [row["user_id"] for row in posts if row.get("user_id")])
    likes = await repository.count_rows_by_post(client, "post_likes", post_ids)
    comments = await repository.count_rows_by_post(client, "post_comments", post_ids)
    liked = await repository.liked_post_ids(client, user_id, post_ids)

    feed: list[FeedPost] = []
    for post in posts:
        profile = profiles.get(post.get("user_id"), {})
        feed.append(
            FeedPost(
                id=post["id"],
                authorId=post.get("user_id"),
                name=profile.get("username") or "Anonymous",
                time=format_post_time(post.get("created_at")),
                content=post.get("content") or "",
                likes=likes.get(post["id"], 0),
                comments=comments.get(post["id"], 0),
                shares=0,
                avatar=profile.get("avatar_url") or DEFAULT_BLOG_AVATAR,
                likedByMe=post["id"] in liked,
            )
        )
    return feed


async def assert_post_owner_or_admin(client: Any, post_id: str, user_id: str, is_admin: bool = False) -> dict[str, Any]:
    post = await repository.get_post(client, post_id)
    if not post or (post.get("user_id") != user_id and not is_admin):
        raise NotFoundError()
    return post


async def assert_comment_owner_or_admin(client: Any, comment_id: str, user_id: str, is_admin: bool = False) -> dict[str, Any]:
    comment = await repository.get_comment(client, comment_id)
    if not comment or (comment.get("user_id") != user_id and not is_admin):
        raise NotFoundError()
    return comment
