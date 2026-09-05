# Blog contracts

The social slice uses `posts`, `post_comments`, and `post_likes`. Tags and
follows were removed by `20260905110138_simplify_schema.sql`.

## `GET /api/v1/posts`

Public. Returns published posts with author display information, comment and
like counts, and the current caller's like state when authenticated.

## `POST /api/v1/posts`

Authenticated. Body: `{ "title": "string?", "content": "string",
"coverImageUrl": "string?" }`. The backend derives `user_id` from the JWT.
Empty content returns `422`.

## `PUT|DELETE /api/v1/posts/{postId}`

Authenticated owner or admin only. An inaccessible or unknown post returns
`404` to avoid leaking its existence.

## `POST|DELETE /api/v1/posts/{postId}/likes`

Authenticated and idempotent on `(post_id, user_id)`. Returns
`{ "liked": true|false, "likeCount": number }`.

## Comment endpoints

- `POST /api/v1/posts/{postId}/comments`
- `PUT|DELETE /api/v1/comments/{commentId}`

The backend derives the comment owner from the JWT and masks inaccessible
comments as `404`.
