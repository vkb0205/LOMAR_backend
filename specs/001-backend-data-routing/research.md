# Phase 0 Research: Backend-Routed Application Data

## R1 — Backend service absent from working tree

**Finding**: `LOMAR_backend/` contains only `.claude/`, `.git/`, `.specify/`,
`specs/`. No `main.py`, `test_api.py`, `Dockerfile`, or dependency manifest
exists, despite:
- `LOMAR/package.json` `dev:backend` script running
  `cd ../LOMAR_backend && python test_api.py`
- The constitution describing a live FastAPI contract
  (`/health`, `/proxy-image`, `/test-try-on`, `/test-try-on-upload`,
  `/consult`)
- Two different, both-stale, GitHub Actions deploy workflows pointing at
  `vton_test_ui/` and `backend/` respectively — neither is `LOMAR_backend/`

**Decision**: Treat this feature as also responsible for standing up the
FastAPI application skeleton that already satisfies Principle I, then adding
data routing on top. This is not optional groundwork — no data endpoint can
exist without a host app.

**Rejected alternative**: Assume the service exists in an unseen branch or
deploy target and write the plan only in terms of "add endpoints." Rejected
because the plan must be executable against the actual repository state.

## R2 — Caller-JWT vs. service-role Supabase access

**Finding**: The current frontend already relies on Supabase RLS admin
override policies (`supabase/legacy/admin_policies.sql`, keyed on
`is_admin()`) rather than a service-role key. FR-009 requires the backend to
enforce access "at least as strictly as today" and forbids relying on
database-level checks as the *only* enforcement point once the backend
mediates.

**Decision**: Default path — every request builds a Supabase client scoped to
the caller's JWT (`Authorization: Bearer <token>` forwarded to PostgREST via
`supabase-py` or raw `httpx`), so RLS still applies as defense-in-depth
exactly per Constitution II. The backend additionally performs its own
ownership/role check in `services/` before issuing the query, so a bug or
future RLS relaxation cannot alone leak data. Service-role key is used only in
`repositories/admin.py` (cross-user admin writes/reads) and
`repositories/analytics.py` (aggregate RPCs with no natural single owner),
each call site commented with why the caller-JWT path is insufficient there.

**Rejected alternative**: Service-role for everything (simpler code, one
Supabase client). Rejected: makes the backend's own authorization logic the
*only* control with RLS fully bypassed everywhere, which is a strictly worse
security posture than today's and conflicts with Principle II's
defense-in-depth framing.

## R3 — Response shape strategy (FR-007)

**Finding**: Frontend mapper functions (e.g. `mapDashboardTasks`,
`mapDashboardVouchers` in [`dashboardService.ts`](../../../LOMAR/src/features/dashboard/services/dashboardService.ts))
already transform raw Supabase rows into view models. Some services return
raw rows directly (`fetchProfiles`, `fetchVendors` in `adminService.ts`).

**Decision**: Backend response bodies mirror whatever shape the *current*
frontend function returned to its caller — raw row arrays where the frontend
mapped nothing itself, and the already-mapped view-model shape where a
frontend mapper existed. The mapper logic itself moves server-side; the
frontend keeps only rendering. This satisfies FR-007 literally ("frontend's
rendering logic does not need to change") while still moving *logic* to the
backend per the feature's stated goal.

**Rejected alternative**: Design new, cleaner DTOs backend-wide. Rejected for
this migration: would require touching rendering code in every feature,
which FR-007 explicitly disallows and which multiplies review surface without
a corresponding requirement asking for it. Can be a follow-up feature.

## R4 — Analytics RPCs

**Finding**: `analyticsService.ts` calls three Postgres RPCs directly:
`record_page_view`, `record_page_engagement` (called by anonymous visitors —
`AnalyticsTracker.tsx` runs on every page, logged in or not), and
`get_admin_website_analytics` (admin-only read, FR-010).

**Decision**: `POST /api/v1/analytics/page-views` and
`POST /api/v1/analytics/page-views/{id}/engagement` stay publicly callable
(no session required), matching FR-006's "publicly readable... analytics
shown to admins" framing extended to the write side that already worked
unauthenticated. `GET /api/v1/admin/analytics` requires verified admin
(FR-010, FR-005). The backend calls the same three RPCs via `httpx`/
`supabase-py` `.rpc()`; no RPC signature changes.

**Rejected alternative**: Require auth on page-view recording. Rejected:
breaks anonymous-visitor analytics that work today (FR-002/SC-002 regression).

## R5 — Error envelope and the "unavailable" contract (SC-005)

**Finding**: Spec edge cases require a "distinguishable error" instead of a
hang or blank screen when the database is unreachable or slow, within the
same time budget users experience today.

**Decision**: Every Supabase-backed call is wrapped with a bounded timeout
(default 8s, configurable via `SUPABASE_TIMEOUT_SECONDS`). On timeout or
connection failure, the backend returns `503` with body
`{"error": {"code": "database_unavailable", "message": "..."}}`. On
validation failure: `422` with `{"error": {"code": "validation_error",
"fields": {...}}}` (FR-008). On auth failure: `401`
`{"error": {"code": "unauthenticated"}}`. On authorization failure: `403`
`{"error": {"code": "forbidden"}}`, except where the spec requires
indistinguishable "not found" behavior for privacy (see R6), which returns
`404` `{"error": {"code": "not_found"}}` instead of `403`. This single error
shape lets frontend code branch on `error.code` once and reuse it everywhere,
which is the "unavailable state" UI referenced by every catalog/dashboard
page.

**Rejected alternative**: Let framework default error pages/502s propagate.
Rejected: violates Constitution V ("actionable HTTP status codes, not hangs")
and gives the frontend nothing structured to render.

## R6 — Admin authorization source and "not found" masking

**Finding**: `profiles.role` carries the canonical
`'customer' | 'vendor' | 'admin'` vocabulary. The spec's edge cases
require that guessing another user's private-record ID returns the same
outcome a legitimate absence would (no "forbidden, but it exists" signal).

**Decision**: `require_admin` dependency loads the caller's profile row by
the JWT `sub` claim and checks `role == 'admin'` on the backend itself
(FR-005 — never trust a client-supplied role claim). For owner-scoped
resources (dashboard rows, chat threads, saved designs), a lookup that finds
a row owned by someone else returns `404`, identical to a genuinely missing
row — never `403` — per the edge-case requirement.

**Rejected alternative**: Trust a `role` claim embedded in the JWT itself.
Rejected: Supabase JWTs are issued at login and do not reliably reflect a
role change made afterward without a forced re-login; FR-005 requires
independent backend verification regardless.

## R7 — File/storage handling

**Finding**: Per spec Assumptions, file/image storage (avatars, vendor
images, AI design assets/outputs) is not a separate story; it moves with the
domain that owns it. `ai_design_assets` and `ai_design_projects.*_image_url`
columns store Supabase Storage URLs; the AI generation flow (`/test-try-on*`)
already runs server-side and already returns URLs.

**Decision**: No new upload endpoints are introduced by this feature beyond
what already exists. Where a domain's data write includes a storage URL
(e.g. saving a design project's `reference_image_url`), the backend accepts
the URL string the same way the frontend's current Supabase insert did;
actual file bytes continue to go through the existing try-on upload path or
direct Supabase Storage client calls, which are out of scope for FR-001's
table list (Storage buckets are not one of the enumerated data domains).

**Rejected alternative**: Proxy all Storage uploads through the backend now.
Rejected: no user story or FR requires it, and it would expand scope beyond
what's testable by this spec's acceptance scenarios.

## R8 — Idempotency for journey-task/voucher upserts

**Finding**: Edge case: near-simultaneous updates from two devices for the
same user/task or user/voucher must not create duplicates; later write wins.
Current frontend already uses `upsert(..., { onConflict: 'user_id,task_id' })`
/ `onConflict: 'user_id,voucher_id'`.

**Decision**: Backend reproduces the same upsert-on-conflict semantics
server-side against the same unique constraints; no new locking or
distributed-coordination mechanism is introduced, since Postgres's own
upsert already gives last-write-wins atomically.

## R9 — Chat persistence failure behavior

**Decision**: When the AI reply succeeds but persistence fails, return the reply with `persisted: false` and a `503 database_unavailable` status/body contract as drafted in `contracts/chat.md`.

**Rationale**: Preserve a successful, user-visible AI response while making history durability explicit; the frontend can warn or retry without treating a generated reply as lost.

**Alternatives considered**: All-or-nothing failure was rejected because it discards a successful AI response and gives users no useful result.
# Schema status

This research record predates the 2026-09-05 schema simplification. The active
table and transport decisions are documented in `data-model.md`; removed-table
references below are historical context only.
