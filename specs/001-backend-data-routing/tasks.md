# Tasks: Backend-Routed Application Data

**Branch**: `001-backend-data-routing` | **Date**: 2026-08-06

**Input**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/),
[quickstart.md](./quickstart.md)

## Conventions

- `[P]` = may run in parallel with other `[P]` tasks in the same phase (no
  shared file, no ordering dependency).
- Every task names the exact file(s) it creates or modifies.
- Backend paths are relative to `LOMAR_backend/`; frontend paths relative to
  `LOMAR/`.
- **Cut-over rule (FR-011)**: within a slice, the frontend swap task and the
  direct-Supabase-deletion task ship in the *same* change set as the backend
  endpoints. A slice is never half-routed.
- Contract tests are written before the implementation they cover and must
  fail first (Constitution VI).

## Phase 1 — Foundation (blocks every slice)

Rationale: `LOMAR_backend/` contains no application code in this tree
(research.md R1). Nothing below can be built without this phase.

- [x] **T001** Create `requirements.txt` pinning FastAPI, Uvicorn, Pydantic v2,
  `pydantic-settings`, `httpx`, `PyJWT[crypto]`, `pytest`, `pytest-asyncio`.
- [x] **T002** [P] Create `Dockerfile`: Python 3.11 slim base, install
  requirements, run Uvicorn bound to `API_HOST`/`API_PORT` (default `8080`),
  non-root user, no secrets baked into layers.
- [x] **T003** [P] Create `app/config.py` with `pydantic-settings` reading
  `API_HOST`, `API_PORT`, `ALLOWED_ORIGINS`, `ENABLE_AUTH`, `SUPABASE_URL`,
  `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`,
  `SUPABASE_TIMEOUT_SECONDS` (default 8), and the existing Google/GenAI vars
  per [quickstart.md](./quickstart.md) §2.
- [x] **T004** Create `app/errors.py`: the single error envelope from
  research.md R5 — `unauthenticated` (401), `forbidden` (403), `not_found`
  (404), `validation_error` (422, with `fields`), `database_unavailable`
  (503) — plus FastAPI exception handlers that guarantee no upstream error
  text or DB detail leaks into the body (data-model.md invariant 9).
- [x] **T005** Create `app/main.py`: FastAPI app, explicit CORS allowlist from
  `ALLOWED_ORIGINS` (never `*`), correlation-ID middleware setting
  `X-Correlation-Id` on every response, and registration of the error handlers
  from T004.
- [x] **T006** Create `app/routers/health.py` — `GET /health` returning the
  existing health response shape with **zero** upstream dependencies
  (Constitution III).
- [x] **T007** Create `app/deps/db.py`: per-request Supabase/PostgREST clients.
  A caller-JWT-scoped client (default, RLS preserved) and a service-role
  client that is only importable by the admin/analytics repositories. Every
  call bounded by `SUPABASE_TIMEOUT_SECONDS`; timeout/connection failure
  raises the `database_unavailable` error from T004 (research.md R2, R5).
- [x] **T008** Create `app/deps/auth.py`: verify the Supabase JWT with
  `SUPABASE_JWT_SECRET` (HS256, `aud`/`exp` checked); `current_user` extracts
  `sub`; `require_customer` rejects anonymous with `401`; `require_admin` performs
  a **fresh backend lookup** of `profiles.role == 'admin'` and never trusts a
  JWT role claim (research.md R6, FR-005). Per plan §Complexity Tracking,
  `/api/v1/me/*` and `/api/v1/admin/*` reject anonymous callers regardless of
  `ENABLE_AUTH`; the flag governs only the pre-existing AI endpoints.
- [x] **T009** Create `tests/conftest.py`: fakes for Supabase (caller and
  service-role) and the AI provider, an ASGI test client over
  `httpx.ASGITransport`, and token factories for anonymous / user A / user B /
  admin. No live network in CI (Constitution VI).
- [x] **T010** [P] Create `tests/contract/test_health.py` — `/health` returns
  200 with the Supabase fake hard-failing, proving dependency-freedom.
- [x] **T011** [P] Create `tests/contract/test_middleware.py` — CORS allowlist
  honored/rejected, `X-Correlation-Id` present on success and error responses,
  Supabase timeout maps to `503 database_unavailable`.
- [x] **T012** [P] Create `tests/unit/test_auth_deps.py` — expired token →
  401; valid token → `sub` resolved; non-admin → 403 from `require_admin`;
  role changed in DB after token issuance is respected (R6).
- [x] **T013** Recreate `app/routers/vton.py` reproducing the existing
  documented contract unchanged (FR-012, Constitution I): `GET /proxy-image`,
  `POST /test-try-on`, `POST /test-try-on-upload` (multipart `body_image`,
  `garment_image`, `category`, `prompt`), `POST /consult` (`{"message"}`).
  Auth on these paths remains governed by `ENABLE_AUTH`.
- [x] **T014** Create `tests/contract/test_vton.py` — AI provider mocked;
  asserts request/response shapes and `ENABLE_AUTH` behavior for the five
  legacy endpoints.
- [ ] **T015** Fix the deploy path (plan §Constitution deviations #2): point
  the active workflow at `./LOMAR_backend`, port `8080`, public config as env
  vars, and `SUPABASE_JWT_SECRET`/`SUPABASE_SERVICE_ROLE_KEY` mounted from
  Secret Manager — never `--set-env-vars`. Retire or correct the stale
  `.github/workflows/deploy-backend.yml` (root, builds `./vton_test_ui`) and
  `LOMAR/.github/workflows/deploy-backend.yml` (builds `./backend`).
- [ ] **T016** [P] Update `LOMAR/package.json` `dev:backend` to launch Uvicorn
  against `app.main:app` instead of the missing `test_api.py`.
- [x] **T017** [P] Create `README.md` documenting every endpoint and env var,
  as the constitution requires.
- [ ] **T018** Extend `LOMAR/src/shared/api/backendClient.ts` with
  `getJson`/`postJson`/`putJson`/`patchJson`/`deleteJson`, automatic
  `Authorization: Bearer <supabase access token>` attachment, `401` → existing
  re-auth/session-expired UX, and `503 database_unavailable` surfaced as a
  typed error the UI renders as the "unavailable" state (SC-005). Add the
  `/api/v1/*` dev proxy target per quickstart.md §4.
- [ ] **T019** Verify against the live Supabase project that the unique
  constraints `(user_id, task_id)`, `(user_id, voucher_id)`,
  `(post_id, user_id)` and the FKs relied on by data-model.md exist. Expected
  outcome: **no migration**. If one is missing, add a single ordered migration
  under `LOMAR/supabase/migrations/` and regenerate
  `LOMAR/src/shared/types/database.ts`. Never create backend-only shadow
  tables.

**Phase 1 checkpoint** — quickstart.md Slice 0: `/health` works with no
upstream, the five legacy endpoints retain behavior, CORS/JWT/timeout/
correlation-ID tests pass, container builds and answers `/health`.

---

## Phase 2 — Slice 1: Catalog (US1, P1)

Contract: [contracts/catalog.md](./contracts/catalog.md). All endpoints
public (FR-006). Establishes the read-path pattern every later slice reuses.

### Tests first

- [x] **T020** [P] Create `tests/contract/test_catalog.py` covering all four
  endpoints: 200 shapes, `404` for unknown vendor and unknown/non-visible
  service, `503 database_unavailable` when the DB fake fails, and that
  anonymous callers succeed.

### Implementation

- [x] **T021** [P] Create `app/schemas/catalog.py` — response models for
  `VendorCard`, `VendorDetail` (`vendor` + `services`), `CustomizeCatalog`
  (`services` + `serviceImages` + `vendors`), and the suggestion payload.
  Shapes mirror what the current frontend functions returned (research.md R3).
- [x] **T022** [P] Create `app/repositories/catalog.py` — caller-JWT client
  queries against `vendors`, `services`, `service_images`; public endpoints
  filter to catalog-visible status per data-model.md.
- [x] **T023** Create `app/routers/catalog.py` — `GET /api/v1/catalog/vendors`,
  `GET /api/v1/catalog/vendors/{vendorId}`, `GET /api/v1/catalog/customize`,
  `GET /api/v1/catalog/services/{serviceId}/suggestion`; register in
  `app/main.py`.

### Frontend cut-over (same change set — FR-011)

- [ ] **T024** [P] Rewrite
  `LOMAR/src/features/vendors/services/vendorCatalogService.ts` to call
  `backendClient`; delete its `supabase.from(...)` calls.
- [ ] **T025** [P] Rewrite
  `LOMAR/src/features/vendors/services/vendorDetailService.ts` likewise.
- [ ] **T026** [P] Rewrite
  `LOMAR/src/features/customize/services/customizeCatalogService.ts` likewise.
- [ ] **T027** [P] Rewrite
  `LOMAR/src/features/ai-consultant/services/serviceSuggestionService.ts`
  likewise.
- [ ] **T028** Run the quickstart.md §6 direct-access grep; confirm zero
  catalog-domain matches. Run `npm run lint` and `npm run build` clean.

**Slice 1 exit** (quickstart.md): services list, vendor detail, and customize
catalog render from the backend; DB-down shows the "unavailable" state.

---

## Phase 3 — Slice 2: Dashboard (US2, P1)

Contract: [contracts/dashboard.md](./contracts/dashboard.md). All
authenticated; `user_id` always derived from the verified JWT.

### Tests first

- [x] **T029** [P] Create `tests/contract/test_dashboard.py`: 200 aggregate
  shape; `401` anonymous and `401` expired token on both `PUT`s; `422` on
  invalid `status`; `404` for unknown `taskId`/`voucherId`; **user B cannot
  read or write user A's rows** (SC-004); repeated/concurrent upserts create
  no duplicates (R8).
- [x] **T030** [P] Create `tests/unit/test_dashboard_mapping.py` — the task and
  voucher status normalization moved out of `dashboardService.ts` produces
  byte-identical view models (FR-007).

### Implementation

- [x] **T031** [P] Create `app/schemas/dashboard.py` — `DashboardData`
  (`tasks`, `vouchers`, `savedDesigns`) and the two `status` request bodies
  with enum validation.
- [x] **T032** [P] Create `app/repositories/dashboard.py` — owner-scoped reads
  across `journey_tasks`, `user_journey_tasks`, `vouchers`, `user_vouchers`,
  `ai_design_projects`; upserts on the existing composite unique constraints.
  Owner-scoped lookups filter by ID **and** caller ID in one query
  (data-model.md invariant 3).
- [x] **T033** Create `app/services/dashboard.py` — join + status
  normalization ported from `dashboardService.ts`; server sets `completed_at`
  / `unlocked_at` and clears them on reversal (invariant 7).
- [x] **T034** Create `app/routers/dashboard.py` — `GET /api/v1/me/dashboard`,
  `PUT /api/v1/me/journey-tasks/{taskId}`, `PUT /api/v1/me/vouchers/{voucherId}`;
  register in `app/main.py`.

### Frontend cut-over

- [ ] **T035** Rewrite
  `LOMAR/src/features/dashboard/services/dashboardService.ts` to call
  `backendClient`; delete its table calls and move-out mappers. Keep
  `celebrateTaskCompletion()` client-side — it is a UI effect, not data.
- [ ] **T036** Run the direct-access grep for the dashboard domain; verify
  user A / user B isolation manually and that task/voucher updates survive
  reload. `npm run lint` clean.

**Slice 2 exit**: tasks/vouchers/saved designs read+write per user; a second
user is provably isolated.

---

## Phase 4 — Slice 3: Blog & social (US3, P2)

Contract: [contracts/social.md](./contracts/social.md).

### Tests first

- [x] **T037** [P] Create `tests/contract/test_social.py`: public feed 200 with
  author/tags/comments; authenticated create/like/comment/follow attributed to
  the caller; like/unlike and follow/unfollow idempotent; **non-owner edit or
  delete returns `404`, never `403`** (existence masking, R6); `422` on empty
  content or unknown `tagIds`.

### Implementation

- [x] **T038** [P] Create `app/schemas/social.py` — feed item, post create/
  update, comment create/update, like and follow payloads.
- [x] **T039** [P] Create `app/repositories/social.py` — `posts`, `tags`,
  `post_tags`, `post_comments`, `post_likes`, `follows`, plus public author
  display fields only from `profiles` (never private fields).
- [x] **T040** Create `app/services/social.py` — ownership resolution shared by
  posts and comments, returning the masked-`404` outcome for non-owner
  non-admin callers; admin callers pass through (no duplicate admin route).
- [x] **T041** Create `app/routers/social.py` — `GET/POST /api/v1/posts`,
  `PUT/DELETE /api/v1/posts/{postId}`,
  `POST/DELETE /api/v1/posts/{postId}/likes`,
  `POST /api/v1/posts/{postId}/comments`,
  `PUT/DELETE /api/v1/comments/{commentId}`, `POST /api/v1/follows`,
  `DELETE /api/v1/follows/{followeeType}/{followeeId}`; register in
  `app/main.py`.

### Frontend cut-over

- [ ] **T042** [P] Rewrite `LOMAR/src/features/blog/services/blogService.ts`;
  carry existing tag/search query parameters over 1:1.
- [ ] **T043** [P] Rewrite
  `LOMAR/src/features/social/services/socialService.ts`.
- [ ] **T044** [P] Rewrite
  `LOMAR/src/features/social/services/followsService.ts`.
- [ ] **T045** Run the direct-access grep for the social domain; exercise the
  US3 acceptance scenarios. `npm run lint` clean.

**Slice 3 exit**: feed public; authoring/like/comment/follow authenticated;
cross-user edit refused.

---

## Phase 5 — Slice 4: Chat history (US4, P2)

Contract: [contracts/chat.md](./contracts/chat.md). AI reply generation is
**unchanged** (FR-012) — only history storage moves.

- [x] **T046** **Resolve the open question in contracts/chat.md**: when
  persistence fails *after* a successful AI reply, does the response return
  the reply with `"persisted": false` (current contract draft) or fail
  all-or-nothing? Decide with product, record the decision in
  [research.md](./research.md), and update the contract before T047.

### Tests first

- [x] **T047** [P] Create `tests/contract/test_chat.py`: message order is
  `created_at ASC, id ASC`; `404` for a thread belonging to another user
  (guessed ID, SC-004); `422` on empty content; assistant messages are
  server-created and cannot be injected by the client; the persistence-failure
  path behaves exactly as decided in T046.

### Implementation

- [x] **T048** [P] Create `app/schemas/chat.py` — `ChatThread`, `ChatMessage`,
  thread-create and message-create bodies.
- [x] **T049** [P] Create `app/repositories/chat.py` — `chat_threads`,
  `chat_messages`, owner-scoped by JWT `sub`; deterministic ordering.
- [x] **T050** Create `app/routers/chat.py` — `POST /api/v1/chat/threads`,
  `GET /api/v1/chat/threads/{threadId}/messages`,
  `POST /api/v1/chat/threads/{threadId}/messages` (store user message → invoke
  the existing unchanged AI path → store assistant reply → return both),
  `GET /api/v1/chat/threads/{threadId}/suggested-service` (passthrough to the
  catalog slice); register in `app/main.py`.

### Frontend cut-over

- [ ] **T051** [P] Rewrite
  `LOMAR/src/features/ai-consultant/services/chatMessageRepository.ts`.
- [ ] **T052** [P] Rewrite
  `LOMAR/src/features/customize/services/customizeChatRepository.ts`.
- [ ] **T053** Remove the inline Supabase queries from
  `LOMAR/src/features/chat/components/FloatingChat.tsx`, routing them through
  the rewritten repositories.
- [ ] **T054** Run the direct-access grep for the chat domain; confirm history
  survives reload in original order and AI replies are unchanged.
  `npm run lint` clean.

**Slice 4 exit**: history persists across reload; AI reply path unchanged.

---

## Phase 6 — Slice 5: Admin + analytics (US5, P3)

Contract: [contracts/admin.md](./contracts/admin.md). Broadest write scope;
lands last and reuses the authorization primitives proven by slices 2–4.

### Tests first

- [x] **T055** [P] Create `tests/contract/test_admin.py`: every
  `/api/v1/admin/*` endpoint returns `403` for an authenticated non-admin and
  `401` for anonymous (SC-003); admin reads/writes succeed; `422` for
  out-of-range `days` and invalid `role`/`status` enums.
- [x] **T056** [P] Create `tests/contract/test_analytics.py`: page-view and
  engagement tracking succeed **anonymously** (no SC-002 regression); a
  client-supplied `user_id` is ignored and only the JWT-derived one is used
  (invariant 10); `GET /api/v1/admin/analytics` is admin-only.

### Implementation

- [x] **T057** [P] Create `app/schemas/admin.py` — metrics, profile/vendor/
  service/post/comment/review list and mutation bodies, journey-task and
  voucher bodies validated by the rules ported from `parseJourneyTaskInsert`/
  `parseJourneyTaskUpdate`/`parseVoucherInsert`/`parseVoucherUpdate`,
  service-request status, generations, and the analytics payloads.
- [x] **T058** [P] Create `app/repositories/admin.py` — cross-user admin reads
  and writes. **Every service-role call site carries a comment justifying why
  the caller-JWT path is insufficient** (Constitution II, research.md R2).
- [x] **T059** [P] Create `app/repositories/analytics.py` — `record_page_view`,
  `record_page_engagement`, `get_admin_website_analytics` invoked with their
  **existing RPC signatures unchanged** (R4); service-role justification
  comments as above.
- [x] **T060** Create `app/routers/admin.py` — all endpoint groups in
  contracts/admin.md, each gated by `require_admin`; register in
  `app/main.py`.
- [x] **T061** Create `app/routers/analytics.py` — public
  `POST /api/v1/analytics/page-views` and
  `POST /api/v1/analytics/page-views/{viewId}/engagement`; `days` bounded
  1–365 on the admin analytics read; register in `app/main.py`.

### Frontend cut-over

- [ ] **T062** [P] Rewrite
  `LOMAR/src/features/admin/services/adminService.ts` to call `backendClient`
  across every panel.
- [ ] **T063** [P] Rewrite
  `LOMAR/src/features/analytics/services/analyticsService.ts`; keep
  `AnalyticsTracker.tsx` firing for anonymous visitors.
- [ ] **T064** [P] Remove the cross-user reads from
  `LOMAR/src/features/auth/services/profileService.ts`, leaving
  `supabase.auth.*` untouched (FR-003).
- [ ] **T065** Shrink `LOMAR/src/shared/api/supabaseClient.ts` to auth,
  session/token helpers, and auth-state subscription **only**.

**Slice 5 exit**: every admin panel served by the backend; non-admin refused
server-side.

---

## Phase 7 — Final verification

- [ ] **T066** Run the quickstart.md §6 gate from the repository root:
  `grep -RInE "supabase\.(from|rpc|storage)" LOMAR/src --include='*.ts' --include='*.tsx'`.
  Only `supabase.auth.*` may remain. This is the mechanical proof of SC-001
  and FR-002.
- [ ] **T067** Execute every acceptance scenario in [spec.md](./spec.md) for
  US1–US5 (SC-002), plus the DB-unreachable path on each affected page
  (SC-005).
- [ ] **T068** Run the full backend suite (`pytest -q`) and frontend
  `npm run lint` + `npm run build`; confirm no live network calls in CI.
- [ ] **T069** Container/deploy verification per quickstart.md §7: build
  `LOMAR_backend`, run it, `curl -f /health`, then dry-run the corrected
  workflow before any production deploy.
- [ ] **T070** Complete the **Post-Design Constitution Re-Check** checklist at
  the bottom of [plan.md](./plan.md) and tick all six boxes. Implementation is
  not done until this is recorded.

---

## Dependencies

- **Phase 1 blocks everything.** No endpoint can exist without the app
  skeleton (research.md R1).
- T004 → T005 (handlers registered on the app). T003 → T007, T008.
  T007 → T008 (`require_admin` needs a DB client). T009 → all contract tests.
- Within each slice: tests → schemas/repositories → services → router →
  frontend swap → grep gate.
- Slices 2–5 depend on Phase 1 only, but **must ship in the stated order** —
  slice order is a risk-sequencing decision in plan.md, not a technical
  dependency. Slice 5 additionally reuses the ownership primitives from
  T040 (slice 3).
- T046 blocks T047 and T050 (contract must be settled before its tests).
- T019 may reveal a missing constraint; if so it blocks T032 (dashboard
  upserts) and T039 (like idempotency).

## Parallelization notes

- Phase 1: T002, T003 run parallel; T010–T012 parallel once T009 lands;
  T016, T017 parallel with anything.
- Each slice: schema and repository tasks are `[P]` (different files); the
  router task serializes them because it registers into `app/main.py`.
- Frontend service rewrites within a slice are `[P]` — one file each — but the
  slice's grep-gate task is always last.
- Do **not** parallelize across slices: FR-011 requires each domain's swap and
  deletion to land together, and a shared `app/main.py` registration point
  makes concurrent router work conflict-prone.

## Traceability

| Requirement | Tasks |
|---|---|
| FR-001 | T021–T023, T031–T034, T038–T041, T048–T050, T057–T061 |
| FR-002 / SC-001 | T028, T036, T045, T054, T065, T066 |
| FR-003 | T065 (auth untouched), T064 |
| FR-004 / SC-004 | T008, T029, T032, T047, T049 |
| FR-005 / SC-003 | T008, T012, T055, T060 |
| FR-006 | T020–T023, T037, T056, T061 |
| FR-007 | T021, T030, T031, T038, T048, T057 |
| FR-008 | T004, T031, T038, T048, T057 |
| FR-009 | T007 (RLS-preserving caller JWT), T040, T058 |
| FR-010 | T059, T061, T056 |
| FR-011 | T028, T036, T045, T054, T065 (per-slice atomic cut-over) |
| FR-012 | T013, T014, T050 |
| SC-005 | T004, T007, T011, T018, T067 |
# Schema status

Completed task descriptions are retained as implementation history. Tasks
that mention tags, follows, reviews, service images, saved designs, or
AI-design generations no longer describe the active schema; see
`data-model.md` and `contracts/`.
