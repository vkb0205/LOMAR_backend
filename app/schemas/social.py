"""Social/blog transport models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FolloweeType(str, Enum):
    user = "user"
    vendor = "vendor"


class FeedPost(BaseModel):
    """Mirrors `BlogPost` in LOMAR/src/features/blog/types.ts (FR-007)."""

    id: str
    authorId: str | None
    name: str
    time: str
    content: str
    tags: str
    likes: int
    comments: int
    shares: int
    avatar: str
    likedByMe: bool


class FeedResponse(BaseModel):
    posts: list[FeedPost]


class PostCreate(BaseModel):
    title: str | None = None
    content: str = Field(min_length=1)
    coverImageUrl: str | None = None
    tagIds: list[str] = Field(default_factory=list)


class PostUpdate(BaseModel):
    title: str | None = None
    content: str | None = Field(default=None, min_length=1)
    coverImageUrl: str | None = None


class CommentCreate(BaseModel):
    content: str = Field(min_length=1)
    parentCommentId: str | None = None


class CommentUpdate(BaseModel):
    content: str = Field(min_length=1)


class LikeResponse(BaseModel):
    liked: bool
    likeCount: int


class FollowCreate(BaseModel):
    followeeType: FolloweeType
    followeeId: str = Field(min_length=1)


class FollowResponse(BaseModel):
    following: bool
    followerCount: int


class MutationResult(BaseModel):
    ok: bool = True


class PostResource(BaseModel):
    post: dict[str, Any]


class CommentResource(BaseModel):
    comment: dict[str, Any]
