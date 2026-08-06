# Contracts overview

All endpoints below are versioned under `/api/v1` except the pre-existing
try-on/consult/health/proxy-image contract, which keeps its current
unversioned paths per Constitution Principle I.

## Conventions

- **Auth header**: `Authorization: Bearer <supabase_access_token>`, forwarded
  exactly as the frontend already attaches it via `withAuthHeaders`.
- **Public** endpoints accept requests with or without the header.
- **Authenticated** endpoints require a valid, unexpired Supabase JWT; missing
  or invalid → `401 { "error": { "code": "unauthenticated" } }`.
- **Admin** endpoints additionally require the backend-verified caller to have
  `profiles.role == 'admin'`; otherwise → `403 { "error": { "code":
  "forbidden" } }` for admin-only *listing* endpoints, or `404 { "error": {
  "code": "not_found" } }` for admin actions on an owner-scoped resource ID
  that also doesn't belong to the caller (existence masking, see
  [research.md](../research.md) R6).
- **Validation failure** → `422 { "error": { "code": "validation_error",
  "fields": { "<field>": "<reason>" } } }`.
- **Upstream/database unavailable** → `503 { "error": { "code":
  "database_unavailable", "message": "..." } }`.
- Every response includes header `X-Correlation-Id`; every error body may
  include `"correlation_id"` for support triage without leaking internals.

## Slice → file map

| Slice | Contract file |
|---|---|
| 1. Catalog (US1) | [catalog.md](./catalog.md) |
| 2. Dashboard (US2) | [dashboard.md](./dashboard.md) |
| 3. Blog & social (US3) | [social.md](./social.md) |
| 4. Chat history (US4) | [chat.md](./chat.md) |
| 5. Admin + analytics (US5) | [admin.md](./admin.md) |

## Existing contract (unchanged, reference only)

| Method | Path | Auth |
|---|---|---|
| GET | `/health` | none (must stay dependency-free) |
| GET | `/proxy-image?url=<encoded>` | per `ENABLE_AUTH` |
| POST | `/test-try-on` | per `ENABLE_AUTH` |
| POST | `/test-try-on-upload` (multipart: `body_image`, `garment_image`, `category`, `prompt`) | per `ENABLE_AUTH` |
| POST | `/consult` (`{ "message": string }`) | per `ENABLE_AUTH` |
