# Blog & social contracts (US3, P2)

Replaces: `blogService.ts`, `socialService.ts`, `followsService.ts`.

## `GET /api/v1/posts`

**Public.** Returns the blog feed with author display info, tags, and
comments as `BlogPage` currently renders. Supports the discovery sidebar's
existing filters (tag/search) if `blogService.ts` already implements them —
carry the same query parameters over 1:1.

**Response 200**: `{ "posts": [{ "...": "current BlogPostCard-consumed shape" }] }`

## `POST /api/v1/posts`

**Authenticated.** Body: `{ "title": "string?", "content": "string",
"coverImageUrl": "string?", "tagIds": ["uuid", "..."] }`. `user_id` forced
from JWT.

**Response 201**: created post in feed-item shape.
**Response 422**: missing `content`, or a `tagIds` entry that doesn't exist.

## `PUT /api/v1/posts/{postId}` / `DELETE /api/v1/posts/{postId}`

**Authenticated, owner or admin only.** Non-owner, non-admin caller → `404`
(existence masked per R6), never `403`, so a probing request can't confirm
the post exists.

## `POST /api/v1/posts/{postId}/likes` / `DELETE /api/v1/posts/{postId}/likes`

**Authenticated.** Idempotent like/unlike keyed on `(post_id, user_id)`.

**Response 200**: `{ "liked": true, "likeCount": 12 }`

## `POST /api/v1/posts/{postId}/comments`

**Authenticated.** Body: `{ "content": "string", "parentCommentId": "uuid?" }`.
`user_id` forced from JWT; `postId`/`parentCommentId` existence validated.

**Response 201**: created comment.
**Response 422**: empty `content`.

## `PUT /api/v1/comments/{commentId}` / `DELETE /api/v1/comments/{commentId}`

**Authenticated, owner or admin only.** Same non-owner masking as posts.

## `POST /api/v1/follows` / `DELETE /api/v1/follows/{followeeType}/{followeeId}`

**Authenticated.** Body for POST: `{ "followeeType": "user|vendor",
"followeeId": "uuid" }`. `follower_id` forced from JWT.

**Response 200**: `{ "following": true, "followerCount": 42 }`

## Authorization summary

| Action | Caller | Result |
|---|---|---|
| Read feed | anyone | 200 |
| Create post/comment/like/follow | authenticated | 201/200, attributed to caller |
| Edit/delete own post/comment | owner | 200 |
| Edit/delete another's post/comment | authenticated non-owner, non-admin | 404 |
| Edit/delete another's post/comment | admin | 200 (admin slice reuses this endpoint; no duplicate admin-only route needed) |
