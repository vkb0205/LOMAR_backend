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
| `ENABLE_AUTH` | no | `false` | Development switch; private `/api/v1/*` routes always require auth |
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

## Endpoint reference

Every response carries `X-Correlation-Id`. Supabase/provider failures use the
sanitized envelope `{ "error": { "code": "...", "message": "..." } }`.

### Liveness and Business Intelligence

| Method | Path | Auth | Body / response |
|---|---|---|---|
| GET | `/health` | none | Existing health shape |
| GET | `/health` | none | Liveness and provider configuration |
| GET | `/api/v1/business-intelligence/overview` | JWT | Metrics, trends, agents, reports, and recommendations |
| POST | `/api/v1/business-intelligence/agents/run` | JWT | Run an analysis agent |
| POST | `/api/v1/business-intelligence/reports` | JWT | Generate a deterministic prototype report |
| POST | `/api/v1/business-intelligence/actions/preview` | JWT | Preview a simulated recommendation action |
| POST | `/api/v1/business-intelligence/chat` | JWT | Grounded BI copilot response |

### Catalog (public)

| Method | Path | Response |
|---|---|---|
| GET | `/api/v1/catalog/vendors` | `{ "vendors": [...] }` |
| GET | `/api/v1/catalog/vendors/{vendorId}` | `{ "vendor": {...}, "services": [...] }` |
| GET | `/api/v1/catalog/services/{serviceId}/suggestion` | `{ "service": {...} }` |
| GET | `/api/v1/catalog/wedding-plans` | `{ "plans": [...] }` (curated packages, active only) |
| GET | `/api/v1/catalog/wedding-plans/{planId}` | `{ "plan": {...}, "items": [...] }` |

Only catalog-visible `active` vendor/service/plan rows are public. `wedding_plans`
bundle multiple catalog services (possibly multi-vendor) into one priced offer;
`wedding_plan_items` link a plan to its services. The couple consultant
(`POST /api/v1/chat/consult`) can discover and inspect these plans via the
`list_wedding_plans` / `get_wedding_plan` agent tools.

### Dashboard (authenticated)

| Method | Path | Body / response |
|---|---|---|
| GET | `/api/v1/me/dashboard` | Dashboard aggregate: tasks, vouchers, saved designs |
| PUT | `/api/v1/me/journey-tasks/{taskId}` | `{ "status": "pending" | "completed" }` → `{ "ok": true }` |
| PUT | `/api/v1/me/vouchers/{voucherId}` | `{ "status": "locked" | "unlocked" }` → `{ "ok": true }` |

Owner IDs come only from the verified JWT. Upserts use existing composite
constraints and server-owned timestamps.

### User wedding-plan acceptance (authenticated)

| Method | Path | Body / response |
|---|---|---|
| PUT | `/api/v1/me/plan-items/{itemType}/{itemId}` | `{ "status": "accepted" \| "declined" \| "removed" }` → `{ "itemType", "itemId", "status", "ok": true }` |

`itemType` is `service` or `plan`. Anonymous calls return `401`, an unknown
item `404`, and an invalid status `422`. The `user_id` is always forced from
the verified JWT and stored owner-scoped (`user_plan_items`); re-accepting the
same item is idempotent. Accepted choices are read through the
security-invoker view `v_user_accepted_plan` (accepted-only, category derived
from `services.category` or `wedding_plans.style`).

When `POST /api/v1/chat/consult` carries a valid JWT, the caller's accepted-plan
summary (categories + counts, no PII) is injected as agent context; anonymous
consults get none. The `get_user_plan` agent tool is read-only — the user, not
the agent, decides.

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

## Manual BI smoke test

Start the backend and frontend in separate terminals:

```bash
# terminal 1
uvicorn app.main:app --reload --port 8080

# terminal 2
cd ../LOMAR
npm run dev
```

Check the public health endpoint:

```bash
curl http://localhost:8080/health
```

Then open `http://localhost:3000/business-intelligence`, sign in with a
Supabase account, and verify that the overview loads. Run an AI agent, generate
a report, preview a recommendation action, and ask the copilot about `past
activities` or `campaign recommendations`. Recommendation previews are
simulations and do not modify business data.

Private BI routes intentionally reject anonymous requests:

```bash
curl -i http://localhost:8080/api/v1/business-intelligence/overview
```

The expected result is `401 Unauthorized`.
