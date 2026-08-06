"""Social/blog HTTP routes — `/api/v1/posts`, `/api/v1/comments`, `/api/v1/follows`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.deps.auth import AuthenticatedUser, current_user, require_user
from app.deps.db import get_supabase
from app.errors import NotFoundError, ValidationError
from app.repositories import social as repository
from app.schemas.social import (
    CommentCreate,
    CommentUpdate,
    FollowCreate,
    FollowResponse,
    LikeResponse,
    MutationResult,
    PostCreate,
    PostUpdate,
)
from app.services import social as service
from app.services.authz import is_platform_admin

router = APIRouter(tags=["social"])


@router.get("/posts")
async def list_posts(
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    client=Depends(get_supabase),
) -> dict[str, list[dict]]:
    feed = await service.build_feed(client, user.user_id)
    return {"posts": [post.model_dump() for post in feed]}


@router.post("/posts", status_code=status.HTTP_201_CREATED)
async def create_post(
    body: PostCreate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> dict:
    await repository.validate_tags(client, body.tagIds)
    post = await repository.create_post(client, user.user_id, body.model_dump())
    return post


@router.put("/posts/{postId}")
async def update_post(
    post_id: Annotated[str, Path(alias="postId", min_length=1)],
    body: PostUpdate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> dict:
    await service.assert_post_owner_or_admin(
        client, post_id, user.user_id, await is_platform_admin(client, user.user_id)
    )
    payload = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if "coverImageUrl" in payload:
        payload["cover_image_url"] = payload.pop("coverImageUrl")
    updated = await repository.update_post(client, post_id, payload)
    if updated is None:
        raise NotFoundError()
    return updated


@router.delete("/posts/{postId}", response_model=MutationResult)
async def delete_post(
    post_id: Annotated[str, Path(alias="postId", min_length=1)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> MutationResult:
    await service.assert_post_owner_or_admin(
        client, post_id, user.user_id, await is_platform_admin(client, user.user_id)
    )
    await repository.delete_by_id(client, "posts", "id", post_id)
    return MutationResult()


@router.post("/posts/{postId}/likes", response_model=LikeResponse)
async def like_post(
    post_id: Annotated[str, Path(alias="postId", min_length=1)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> LikeResponse:
    if not await repository.post_exists(client, post_id):
        raise NotFoundError()
    await repository.toggle_like(client, user.user_id, post_id, liked=False)
    return LikeResponse(liked=True, likeCount=await repository.like_count(client, post_id))


@router.delete("/posts/{postId}/likes", response_model=LikeResponse)
async def unlike_post(
    post_id: Annotated[str, Path(alias="postId", min_length=1)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> LikeResponse:
    if not await repository.post_exists(client, post_id):
        raise NotFoundError()
    await repository.toggle_like(client, user.user_id, post_id, liked=True)
    return LikeResponse(liked=False, likeCount=await repository.like_count(client, post_id))


@router.post("/posts/{postId}/comments", status_code=status.HTTP_201_CREATED)
async def create_comment(
    post_id: Annotated[str, Path(alias="postId", min_length=1)],
    body: CommentCreate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> dict:
    if not await repository.post_exists(client, post_id):
        raise NotFoundError()
    if body.parentCommentId is not None:
        parent = await repository.get_comment(client, body.parentCommentId)
        if parent is None:
            raise ValidationError(fields={"parentCommentId": "Unknown parent comment."})
    return await repository.create_comment(client, user.user_id, post_id, body.model_dump())


@router.put("/comments/{commentId}")
async def update_comment(
    comment_id: Annotated[str, Path(alias="commentId", min_length=1)],
    body: CommentUpdate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> dict:
    await service.assert_comment_owner_or_admin(
        client, comment_id, user.user_id, await is_platform_admin(client, user.user_id)
    )
    updated = await repository.update_comment(client, comment_id, body.content)
    if updated is None:
        raise NotFoundError()
    return updated


@router.delete("/comments/{commentId}", response_model=MutationResult)
async def delete_comment(
    comment_id: Annotated[str, Path(alias="commentId", min_length=1)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> MutationResult:
    await service.assert_comment_owner_or_admin(
        client, comment_id, user.user_id, await is_platform_admin(client, user.user_id)
    )
    await repository.delete_by_id(client, "post_comments", "id", comment_id)
    return MutationResult()


@router.get("/follows/{followeeType}/{followeeId}", response_model=FollowResponse)
async def get_follow_state(
    followee_type: Annotated[str, Path(alias="followeeType")],
    followee_id: Annotated[str, Path(alias="followeeId", min_length=1)],
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    client=Depends(get_supabase),
) -> FollowResponse:
    """Follower count (public) plus this caller's follow state, if any.

    Public like the feed: an anonymous caller gets the count with
    ``following: false`` rather than a 401, so a logged-out visitor can still
    see follower numbers on a vendor or profile page.
    """
    if followee_type not in ("user", "vendor"):
        raise ValidationError(fields={"followeeType": "Must be 'user' or 'vendor'."})
    following = False
    if user.user_id:
        following = bool(
            await repository.follow_rows(client, user.user_id, followee_type, followee_id)
        )
    count = await repository.follow_count(client, followee_type, followee_id)
    return FollowResponse(following=following, followerCount=count)


@router.post("/follows", response_model=FollowResponse)
async def create_follow(
    body: FollowCreate,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> FollowResponse:
    if not await repository.target_exists(client, body.followeeType.value, body.followeeId):
        raise ValidationError(fields={"followeeId": "Target does not exist."})
    await repository.create_follow(client, user.user_id, body.followeeType.value, body.followeeId)
    count = await repository.follow_count(client, body.followeeType.value, body.followeeId)
    return FollowResponse(following=True, followerCount=count)


@router.delete("/follows/{followeeType}/{followeeId}", response_model=FollowResponse)
async def delete_follow(
    followee_type: Annotated[str, Path(alias="followeeType")],
    followee_id: Annotated[str, Path(alias="followeeId", min_length=1)],
    user: Annotated[AuthenticatedUser, Depends(require_user)],
    client=Depends(get_supabase),
) -> FollowResponse:
    if followee_type not in ("user", "vendor"):
        raise ValidationError(fields={"followeeType": "Must be 'user' or 'vendor'."})
    await repository.delete_follow(client, user.user_id, followee_type, followee_id)
    count = await repository.follow_count(client, followee_type, followee_id)
    return FollowResponse(following=False, followerCount=count)
