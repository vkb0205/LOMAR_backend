# LOMAR Backend

FastAPI service routing LOMAR application data through the existing Supabase
project. Supabase Auth remains in the frontend; application data requests use
`Authorization: Bearer <supabase access token>`.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8080}"
```

`GET /health` is dependency-free and needs no Supabase configuration.

## Environment

| Variable | Required | Default | Purpose |
|---|---:|---|---|
| `API_HOST` | no | `0.0.0.0` | Bind address |
| `API_PORT` | no | `8080` | HTTP port |
| `ALLOWED_ORIGINS` | no | `http://localhost:3000` | Comma-separated CORS allowlist; `*` forbidden |
| `ENABLE_AUTH` | no | `false` | Gates legacy AI routes only; `/api/v1/me/*` and `/api/v1/admin/*` always require auth |
| `SUPABASE_URL` | data routes | empty | Existing Supabase project URL |
| `SUPABASE_ANON_KEY` | data routes | empty | Caller-JWT/anon PostgREST key |
| `SUPABASE_SERVICE_ROLE_KEY` | admin analytics | empty | Secret Manager only; never commit or pass as public env config |
| `SUPABASE_JWT_SECRET` | authenticated routes | empty | HS256 Supabase JWT secret; Secret Manager only |
| `SUPABASE_JWT_AUDIENCE` | no | `authenticated` | JWT audience |
| `SUPABASE_TIMEOUT_SECONDS` | no | `8` | Per-operation DB timeout |
| `GOOGLE_GENAI_USE_VERTEXAI` | AI | `false` | Select Vertex mode |
| `GOOGLE_API_KEY` | API-key AI | empty | GenAI API key |
| `GOOGLE_CLOUD_PROJECT` | Vertex AI | empty | GCP project |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI | `global` | Vertex location |
| `GOOGLE_TEXT_MODEL` | no | `gemini-2.5-flash` | Consultant model |
| `NANO_BANANA_MODEL` | image AI | empty | Image model |

## Endpoint reference

Every response carries `X-Correlation-Id`. Supabase/provider failures use the
sanitized envelope `{ "error": { "code": "...", "message": "..." } }`.

### Liveness and legacy AI

| Method | Path | Auth | Body / response |
|---|---|---|---|
| GET | `/health` | none | Existing health shape |
| GET | `/proxy-image?url=<encoded>` | `ENABLE_AUTH` | Validated image proxy |
| POST | `/test-try-on` | `ENABLE_AUTH` | JSON image URL request; image URL response |
| POST | `/test-try-on-upload` | `ENABLE_AUTH` | Multipart `body_image`, `garment_image`, `category`, `prompt` |
| POST | `/consult` | `ENABLE_AUTH` | `{ "message": "..." }` → `{ "reply": "..." }` |

### Catalog (public)

| Method | Path | Response |
|---|---|---|
| GET | `/api/v1/catalog/vendors` | `{ "vendors": [...] }` |
| GET | `/api/v1/catalog/vendors/{vendorId}` | `{ "vendor": {...}, "services": [...] }` |
| GET | `/api/v1/catalog/customize` | `{ "services": [...], "serviceImages": [...], "vendors": [...] }` |
| GET | `/api/v1/catalog/services/{serviceId}/suggestion` | `{ "service": {...} }` |

Only catalog-visible `active` vendor/service rows are public.

### Dashboard (authenticated)

| Method | Path | Body / response |
|---|---|---|
| GET | `/api/v1/me/dashboard` | Dashboard aggregate: tasks, vouchers, saved designs |
| PUT | `/api/v1/me/journey-tasks/{taskId}` | `{ "status": "pending" | "completed" }` → `{ "ok": true }` |
| PUT | `/api/v1/me/vouchers/{voucherId}` | `{ "status": "locked" | "unlocked" }` → `{ "ok": true }` |

Owner IDs come only from the verified JWT. Upserts use existing composite
constraints and server-owned timestamps.

### Social (feed public; mutations authenticated)

| Method | Path |
|---|---|
| GET | `/api/v1/posts` |
| POST | `/api/v1/posts` |
| PUT/DELETE | `/api/v1/posts/{postId}` |
| POST/DELETE | `/api/v1/posts/{postId}/likes` |
| POST | `/api/v1/posts/{postId}/comments` |
| PUT/DELETE | `/api/v1/comments/{commentId}` |
| POST | `/api/v1/follows` |
| DELETE | `/api/v1/follows/{followeeType}/{followeeId}` |

Non-owner post/comment mutation is masked as `404`.

### Chat (authenticated)

| Method | Path |
|---|---|
| POST | `/api/v1/chat/threads` |
| GET | `/api/v1/chat/threads/{threadId}/messages` |
| POST | `/api/v1/chat/threads/{threadId}/messages` |
| GET | `/api/v1/chat/threads/{threadId}/suggested-service` |

History orders by `created_at ASC, id ASC`. Assistant messages are always
server-created. If AI succeeds but persistence fails, contract returns the
reply with `persisted: false` and sanitized `503 database_unavailable`.

### Admin and analytics

All `/api/v1/admin/*` routes require a fresh `profiles.role == 'admin'`
lookup. Public tracking keeps anonymous behavior:

- `POST /api/v1/analytics/page-views`
- `POST /api/v1/analytics/page-views/{viewId}/engagement`

Admin aggregate: `GET /api/v1/admin/analytics?days=1..365`.

Admin lists/mutations cover profiles, vendors, services, posts, comments,
reviews, journey tasks, vouchers, service requests, and generations. Admin
cross-user calls use the service-role repository only after `require_admin`.

## Tests

```bash
pytest -q
```

Tests use `tests.fakes.FakeSupabase`; no live network or production data.
