# Chat history contracts (US4, P2)

Replaces: `chatMessageRepository.ts`, `customizeChatRepository.ts`, and the
inline Supabase calls in `FloatingChat.tsx`. Does **not** change how AI
replies are generated (`/consult`, try-on endpoints unchanged, FR-012) — only
where message history is stored/read.

All endpoints **authenticated**; threads and messages are owner-scoped.

## `GET /api/v1/chat/threads/{threadId}/messages`

Returns prior messages in original order (`created_at ASC, id ASC`).

**Response 200**: `{ "messages": [{ "id": "uuid", "role": "user|assistant",
"content": "string", "createdAt": "iso", "suggestedServiceId": "uuid?" }] }`
**Response 404**: thread doesn't exist or belongs to another user (masked).

## `POST /api/v1/chat/threads`

Creates or resolves a thread for the given context (consultant vs.
customization; optional `vendorId`/`serviceId`/`designProjectId`), mirroring
`chat_threads.context_type` usage today.

**Response 201**: `{ "threadId": "uuid" }`

## `POST /api/v1/chat/threads/{threadId}/messages`

Body: `{ "content": "string" }`. Backend stores the user's message, invokes
the existing AI reply path (unchanged), then stores the assistant's reply
attributed to the same user, and returns both.

**Response 200**
```json
{
  "userMessage": { "...": "ChatMessage" },
  "assistantMessage": { "...": "ChatMessage" }
}
```

**Response 422**: empty `content`.
**Response 503** (T046 decision, research.md R9): when the AI reply succeeds
but persistence fails, return HTTP `503` with the generated reply still in the
body and `"persisted": false`, alongside the standard `database_unavailable`
error envelope, so the frontend can show the reply and warn that history may
not survive reload.

```json
{
  "userMessage": { "...": "ChatMessage" },
  "assistantMessage": { "...": "ChatMessage" },
  "persisted": false,
  "error": { "code": "database_unavailable", "message": "..." }
}
```

Successful responses include `"persisted": true`.

## `GET /api/v1/chat/threads/{threadId}/suggested-service`

Thin passthrough to the catalog slice's suggestion lookup when a chat
message references a suggested service, per US4 acceptance scenario 3.

**Response 200**: `{ "service": { "...": "ServiceRow" } }`
