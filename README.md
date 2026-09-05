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
| `ENABLE_AUTH` | no | `false` | Controls API documentation exposure; route security is dependency-based |
| `SUPABASE_URL` | data routes | empty | Existing Supabase project URL |
| `SUPABASE_ANON_KEY` | data routes | empty | Caller-JWT/anon PostgREST key |
| `SUPABASE_SERVICE_ROLE_KEY` | admin analytics | empty | Secret Manager only; never commit or pass as public env config |
| `SUPABASE_JWT_SECRET` | authenticated routes | empty | HS256 Supabase JWT secret; Secret Manager only |
| `SUPABASE_JWT_AUDIENCE` | no | `authenticated` | JWT audience |
| `SUPABASE_TIMEOUT_SECONDS` | no | `8` | Per-operation DB timeout |
| `AI_TEXT_PROVIDER` | no | `openai` | Text provider: `openai` (any OpenAI-compatible API) or `google` |
| `OPENAI_API_KEY` | OpenAI provider | empty | Key for the OpenAI-compatible API (e.g. OpenAI, DeepSeek, OpenRouter, local gateway) |
| `OPENAI_BASE_URL` | no | empty | Optional `base_url` override for OpenAI-compatible endpoints (e.g. `https://api.deepseek.com/v1`); empty = default OpenAI endpoint |
| `AI_TEXT_MODEL` | no | empty | Model name passed verbatim (e.g. `gpt-4o-mini`, `deepseek-chat`); falls back to `GOOGLE_TEXT_MODEL` |
| `GOOGLE_GENAI_USE_VERTEXAI` | google provider | `false` | Select Vertex mode |
| `GOOGLE_API_KEY` | google provider | empty | GenAI API key |
| `GOOGLE_CLOUD_PROJECT` | google provider | empty | GCP project |
| `GOOGLE_CLOUD_LOCATION` | google provider | `global` | Vertex location |
| `GOOGLE_TEXT_MODEL` | no | `gemini-2.5-flash` | Consultant model fallback for the text provider |
| `NANO_BANANA_MODEL` | image AI | empty | Image model |

## Endpoint reference

Every response carries `X-Correlation-Id`. Supabase/provider failures use the
sanitized envelope `{ "error": { "code": "...", "message": "..." } }`.

### Router groups

| Group | Policy | Included domains |
|---|---|---|
| Public | No JWT required | Health, catalog, public social reads, analytics |
| Customer | Exact `profiles.role = customer` | Profile, dashboard, chat |
| Vendor | Exact `profiles.role = vendor` | Owned services, requests, vouchers |
| Admin | Exact `profiles.role = admin` | Platform administration |

`/health` remains dependency-free. Legacy VTON routes (`/proxy-image`,
`/test-try-on*`, and `/consult`) are retired and are not mounted.

### Catalog (public)

| Method | Path | Response |
|---|---|---|
| GET | `/api/v1/catalog/vendors` | `{ "vendors": [...] }` |
| GET | `/api/v1/catalog/vendors/{vendorId}` | `{ "vendor": {...}, "services": [...] }` |
| GET | `/api/v1/catalog/customize` | `{ "services": [...], "vendors": [...] }` |
| GET | `/api/v1/catalog/services/{serviceId}/suggestion` | `{ "service": {...} }` |

Only catalog-visible `active` vendor/service rows are public.

### Dashboard (authenticated)

| Method | Path | Body / response |
|---|---|---|
| GET | `/api/v1/me/dashboard` | Dashboard aggregate: tasks and vouchers |
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
journey tasks, vouchers, and service requests. Admin
cross-user calls use the service-role repository only after `require_admin`.

## Tests

```bash
pytest -q
```

Tests use `tests.fakes.FakeSupabase`; no live network or production data.
