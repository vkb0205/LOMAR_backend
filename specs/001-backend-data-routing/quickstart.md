# Quickstart: Backend-Routed Application Data

## 1. Prerequisites

- Python 3.11+
- Node.js/npm compatible with [`LOMAR/package.json`](../../../LOMAR/package.json)
- Supabase project URL and keys for the same project used by
  `VITE_SUPABASE_URL`
- A Supabase test user, plus a separate admin test user whose `profiles.role`
  is `admin`
- Docker for container verification (optional locally, required in CI)

No production credentials belong in `.env` committed to either repository.

## 2. Backend environment

Create `LOMAR_backend/.env` locally:

```dotenv
API_HOST=0.0.0.0
API_PORT=8080
ALLOWED_ORIGINS=http://localhost:3000
ENABLE_AUTH=true
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_ANON_KEY=<local-development-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<local-development-service-role-key>
SUPABASE_JWT_SECRET=<local-development-jwt-secret>
SUPABASE_TIMEOUT_SECONDS=8
GOOGLE_GENAI_USE_VERTEXAI=false
GOOGLE_API_KEY=<local-development-key>
GOOGLE_TEXT_MODEL=gemini-2.5-flash
NANO_BANANA_MODEL=<configured-image-model>
```

Production values come from Cloud Run environment configuration and Secret
Manager. `SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_JWT_SECRET` must never be
passed through a visible `--set-env-vars` argument.

## 3. Install and run

From [`LOMAR_backend/`](../../):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" --reload
```

Health check must work without Supabase:

```bash
curl -i http://localhost:8080/health
```

Expected: `200` and the existing health response shape.

Run backend tests:

```bash
pytest -q
```

Run frontend checks from [`LOMAR/`](../../../LOMAR/):

```bash
npm ci
npm run lint
npm run build
```

Update `LOMAR/package.json` `dev:backend` only after the new FastAPI entrypoint
exists; it should launch Uvicorn, not a missing `test_api.py` script.

## 4. Frontend local routing

Development frontend calls the backend through the existing `/api/vton/*`
Vite proxy for legacy AI paths. Add a matching `/api/v1/*` proxy target to the
Vite configuration, or configure `VITE_BACKEND_URL` through the shared
`resolveBackendEndpoint`/`backendClient` path. Production calls the deployed
backend URL directly with the existing `VITE_VTON_BACKEND_URL` mechanism until
a separately named API URL is introduced.

Required frontend behavior:

- `supabaseClient.ts` retains only `supabase.auth.*`, session/token helpers,
  and auth-state subscription code.
- Feature data services call `backendClient`.
- No migrated module contains `supabase.from(...)`, `supabase.rpc(...)`, or
  `supabase.storage.*` for a migrated domain.
- Every authenticated request attaches the current Supabase access token.
- `401` triggers the existing re-auth/session-expired UX.
- `503` with `database_unavailable` renders a visible unavailable state.

## 5. Slice verification

Run each checklist only after the previous slice has passed.

### Slice 0 — Existing backend contract

- [ ] `GET /health` works with no upstream dependency.
- [ ] `/proxy-image`, `/test-try-on`, `/test-try-on-upload`, `/consult` retain
      existing request/response behavior.
- [ ] AI provider mocked tests pass.
- [ ] CORS, JWT, timeout, correlation-ID tests pass.

### Slice 1 — Catalog

- [ ] Anonymous `GET /api/v1/catalog/vendors` returns the current catalog.
- [ ] Anonymous vendor detail and customize catalog render unchanged.
- [ ] Service suggestion lookup works.
- [ ] DB failure produces `503/database_unavailable` and visible UI state.
- [ ] Direct Supabase table calls deleted from the four catalog services.

### Slice 2 — Dashboard

- [ ] User A sees only User A dashboard rows.
- [ ] User B cannot retrieve User A dashboard, design, task, or voucher rows.
- [ ] Task and voucher updates persist after reload.
- [ ] Repeated/concurrent upserts do not duplicate rows.
- [ ] Expired token returns `401`; UI prompts re-authentication.
- [ ] `dashboardService.ts` has no direct table calls.

### Slice 3 — Blog/social

- [ ] Anonymous feed includes author, tags, comments.
- [ ] Authenticated create/like/comment/follow succeeds.
- [ ] Like/unlike and follow/unfollow are idempotent.
- [ ] User B cannot edit/delete User A's post/comment.
- [ ] `blogService.ts`, `socialService.ts`, and `followsService.ts` have no
      direct table calls.

### Slice 4 — Chat

- [ ] Existing consultant/customization chat replies remain unchanged.
- [ ] History reload preserves message order.
- [ ] User B cannot read User A's thread by guessed ID.
- [ ] Suggested service data comes through backend.
- [ ] Both chat repositories and inline chat queries have no direct table
      calls.

### Slice 5 — Admin and analytics

- [ ] Admin user can load every existing admin panel.
- [ ] Admin edits/deletes persist.
- [ ] Customer and anonymous callers receive `403`/`401` for admin routes.
- [ ] Admin analytics returns existing metrics/date-range behavior.
- [ ] Anonymous page-view tracking still works.
- [ ] `adminService.ts`, `analyticsService.ts`, and migrated profile reads have
      no direct application-data calls.

## 6. Direct-access gate

Before each slice merges, run from repository root:

```bash
grep -RInE "supabase\\.(from|rpc|storage)" LOMAR/src --include='*.ts' --include='*.tsx'
```

Remaining matches must be limited to:

- `supabase.auth.*` authentication/session operations
- unmigrated domains explicitly listed in the current slice checklist

After Slice 5, only auth/session calls may remain. This is the mechanical gate
for SC-001 and FR-002.

## 7. Container/deploy verification

```bash
docker build -t lomar-backend:local LOMAR_backend
docker run --rm -p 8080:8080 \
  -e API_HOST=0.0.0.0 \
  -e API_PORT=8080 \
  lomar-backend:local
curl -f http://localhost:8080/health
```

Update the active backend workflow to build `./LOMAR_backend`, deploy port
`8080`, inject public configuration as environment variables, and mount
`SUPABASE_JWT_SECRET`/other secrets through Secret Manager. Verify the same
workflow path in a dry run before production deployment.

## 8. Rollback

Rollback is domain-atomic, not request-by-request:

1. Stop rollout before deleting the frontend direct calls for the next slice.
2. If a completed slice fails, revert its frontend service swap and backend
   route together in one deployment; do not activate both paths for the same
   domain.
3. Keep schema migrations backward-compatible and additive if any are needed.
4. Re-run the slice's contract and acceptance checks before retrying.

Authentication remains direct to Supabase throughout rollback; only
application-data routes are toggled.
# Schema status

The active verification surface excludes tags, follows, reviews, service
images, and AI-design data. See `data-model.md` and `contracts/` for current
responses.
