# Implementation Plan: Backend-Routed Application Data

**Branch**: `001-backend-data-routing` | **Date**: 2026-08-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-backend-data-routing/spec.md`

## Summary

Move every application-data read and write out of the browser's Supabase
client and behind an HTTP API owned by `LOMAR_backend/`. The frontend keeps
Supabase **Auth** (sign-in/up/out, session refresh) exactly as today and sends
the resulting JWT as `Authorization: Bearer <token>` to the backend. The
backend verifies that JWT, resolves the caller's profile and role, and
performs data access against the same Supabase Postgres project — using the
caller's JWT (RLS-preserving) for user-scoped work and the service-role key
only where an operation provably cannot run under RLS.

Delivered as five independently shippable domain slices matching the spec's
prioritized user stories: catalog (P1), dashboard (P1), blog/social (P2),
chat history (P2), admin (P3). Each slice ships backend endpoints + contract
tests first, then flips the matching frontend service module, then deletes
that domain's direct Supabase table access in the same change (FR-011).

Critical, plan-shaping repository fact: **`LOMAR_backend/` contains no
application code today** — only `.specify/`, `.claude/`, and `specs/`. The
FastAPI service described by the constitution (`/health`, `/proxy-image`,
`/test-try-on`, `/test-try-on-upload`, `/consult`) is *not* present in this
working tree, though the frontend and the deploy workflow both reference it.
Phase 1 of this plan therefore includes scaffolding/recovering that service
before any data endpoint is added. See [research.md](./research.md) R1.

## Technical Context

**Language/Version**: Python 3.11+ (constitution: "Python with FastAPI")

**Primary Dependencies**: FastAPI, Uvicorn, Pydantic v2, `supabase-py` (or
`httpx` against PostgREST), `PyJWT[crypto]` for Supabase JWT verification,
`pytest` + `httpx.ASGITransport` for contract tests

**Storage**: Existing Supabase Postgres project (the one
`VITE_SUPABASE_URL` points at). No new datastore. Schema changes, if any, as
ordered migrations in `LOMAR/supabase/migrations/`.

**Testing**: `pytest` contract tests per endpoint with Supabase and the AI
provider mocked; no live network in CI (Constitution VI)

**Target Platform**: Google Cloud Run container, `us-central1`, project
`lomar-500117`, service `lomar-vton-backend`

**Project Type**: Web application — Vite/React frontend in `LOMAR/`, HTTP API
in `LOMAR_backend/`

**Performance Goals**: Catalog and dashboard reads p95 ≤ 500 ms server-side
excluding cold start; no endpoint fans out to more than the number of
Supabase round-trips the frontend performs today for the same screen

**Constraints**: Stateless (Constitution III); response bodies must map 1:1
onto the shapes existing frontend mappers consume (FR-007); every upstream
call bounded by an explicit timeout with a defined failure path
(Constitution V, SC-005); no secrets in the repository

**Scale/Scope**: ~23 tables, 5 domain slices, ~40 endpoints, ~14 frontend
service modules rewritten, single-region deployment

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.0.0.*

| Principle | Status | How this plan satisfies it |
|---|---|---|
| I. Frontend Contract Is Law | PASS (with expansion) | Existing endpoints (`/health`, `/proxy-image`, `/test-try-on`, `/test-try-on-upload`, `/consult`) keep their shapes untouched (FR-012). New data endpoints are additive. Each frontend service swap ships in the same change as its endpoint, as Principle I requires for coordinated changes. |
| II. Supabase Is The System Of Record | PASS | No new primary datastore, no caches, no duplicated business tables. RLS stays enabled and is the default execution path (caller-JWT). Service-role use is exception-only and must carry a justifying code comment. |
| III. Stateless, Container-Native | PASS | No request state in memory; per-request Supabase client bound to the caller's token. Binds `API_HOST`/`API_PORT`; `/health` stays dependency-free. |
| IV. Secure By Default | PASS (tightened) | This feature makes `ENABLE_AUTH=true` mandatory in production, because user-scoped data endpoints cannot be safely served open. See Complexity Tracking. Explicit CORS allowlist, typed Pydantic validation on every payload, no upstream error text leaked. |
| V. Observability & Graceful Degradation | PASS | Correlation ID per request; Supabase failures map to `503` with a stable machine-readable code so the frontend can render the "unavailable" state (SC-005) instead of hanging. |
| VI. Test The Contract, Not The Model | PASS | Every new endpoint gets a contract test (status codes, validation, response shape) with Supabase mocked. Authorization negatives (non-owner, non-admin, anonymous) are contract tests too, covering SC-003/SC-004. |

**Post-Phase-1 re-check**: required before implementation begins; recorded at
the bottom of this file.

### Constitution deviations requiring attention

1. **`ENABLE_AUTH` may not remain optional.** The constitution says the
   service "MAY run open" when `ENABLE_AUTH=false`, and endpoints "MUST still
   function for unauthenticated callers." That is safe for try-on but unsafe
   for `/api/v1/me/*` and `/api/v1/admin/*`. Resolution: user-scoped and admin
   endpoints reject unauthenticated callers with `401` *regardless* of
   `ENABLE_AUTH`; the flag continues to govern only the pre-existing AI
   endpoints. This narrows, never widens, access. Logged in Complexity
   Tracking.
2. **Stale deploy path.** Root `.github/workflows/deploy-backend.yml` builds
   `./vton_test_ui`; `LOMAR/.github/workflows/deploy-backend.yml` builds
   `./backend`. Neither points at `LOMAR_backend/`. The constitution already
   flags this as MUST-fix before the next deploy. Included as a Phase 1 task.

## Project Structure

### Documentation (this feature)

```text
specs/001-backend-data-routing/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── README.md
│   ├── catalog.md
│   ├── dashboard.md
│   ├── social.md
│   ├── chat.md
│   └── admin.md
├── checklists/
│   └── requirements.md  # existing
└── tasks.md             # Phase 2, created by /speckit.tasks — NOT by this command
```

### Source Code (repository root)

```text
LOMAR_backend/
├── Dockerfile
├── requirements.txt
├── README.md                     # endpoint docs required by the constitution
├── app/
│   ├── main.py                   # FastAPI app, CORS, correlation-ID middleware
│   ├── config.py                 # env-var settings (pydantic-settings)
│   ├── errors.py                 # error envelope + exception handlers
│   ├── deps/
│   │   ├── auth.py               # JWT verify, current_user, require_admin
│   │   └── db.py                 # per-request Supabase clients (caller / service)
│   ├── schemas/                  # Pydantic request + response models per domain
│   │   ├── catalog.py
│   │   ├── dashboard.py
│   │   ├── social.py
│   │   ├── chat.py
│   │   └── admin.py
│   ├── repositories/             # PostgREST/Supabase query code, no HTTP types
│   │   ├── catalog.py
│   │   ├── dashboard.py
│   │   ├── social.py
│   │   ├── chat.py
│   │   ├── admin.py
│   │   └── analytics.py
│   ├── services/                 # domain rules: ownership, task/voucher logic
│   └── routers/
│       ├── health.py             # existing contract
│       ├── vton.py               # existing: /proxy-image, /test-try-on*, /consult
│       ├── catalog.py            # /api/v1/catalog/*
│       ├── dashboard.py          # /api/v1/me/*
│       ├── social.py             # /api/v1/posts/*, /api/v1/follows/*
│       ├── chat.py               # /api/v1/chat/*
│       ├── analytics.py          # /api/v1/analytics/*
│       └── admin.py              # /api/v1/admin/*
└── tests/
    ├── conftest.py               # Supabase + AI provider fakes
    ├── contract/                 # one module per router
    └── unit/                     # mappers, ownership rules

LOMAR/
├── src/shared/api/
│   ├── supabaseClient.ts         # SHRINKS to auth + token helpers only
│   ├── backendClient.ts          # GROWS: getJson/postJson/patchJson/deleteJson
│   └── backendConfig.ts          # unchanged resolution strategy
└── src/features/*/services/      # each rewritten to call backendClient
```

**Structure Decision**: Web-application layout. The backend keeps its own
directory per the constitution's repository boundary rule and is never
vendored into the Vite tree. Inside the backend, routers/schemas/repositories
are split by the same five domain slices used for sequencing, so one slice's
work touches one router, one schema module, one repository module, and one
contract-test module.

## Phase 0 — Research

Open decisions are recorded and resolved in [research.md](./research.md):

- **R1** Backend service does not exist in this tree — scaffold vs. recover
- **R2** Caller-JWT PostgREST vs. service-role access (RLS strategy)
- **R3** Response shape strategy for FR-007 (raw rows vs. mapped view models)
- **R4** Analytics RPCs (`record_page_view`, `record_page_engagement`,
  `get_admin_website_analytics`) — who may call them, anonymously or not
- **R5** Error envelope and the `503` "unavailable" contract for SC-005
- **R6** Admin authorization source (`profiles.role`) and its trust boundary
- **R7** Storage/file uploads — which domain owns them and how they route
- **R8** Idempotency for journey-task and voucher upserts (last-write-wins)

## Phase 1 — Design outputs

- [data-model.md](./data-model.md): the 23 tables in play, ownership column,
  visibility class (public / owner-scoped / admin-only), and which slice owns
  each.
- [contracts/](./contracts/): per-slice endpoint contracts — method, path,
  auth requirement, request model, response model, error codes.
- [quickstart.md](./quickstart.md): local run, env vars, how to verify a slice
  end-to-end, and the per-slice cut-over checklist enforcing FR-011.

### Cut-over rule (FR-011, non-negotiable)

For each slice, in order, in one change set:

1. Backend endpoints merged, contract tests green.
2. Frontend service module rewritten to call those endpoints.
3. That domain's `supabase.from(...)` / `supabase.rpc(...)` calls deleted.
4. `npm run lint` (`tsc --noEmit`) clean; the domain's acceptance scenarios
   from the spec exercised manually.

A slice is never half-routed. `supabase.auth.*` is explicitly out of scope and
stays in the frontend (FR-003).

### Slice order and exit criteria

| Slice | Spec story | Frontend modules retired | Exit criterion |
|---|---|---|---|
| 1. Catalog | US1 (P1) | `vendorCatalogService`, `vendorDetailService`, `customizeCatalogService`, `serviceSuggestionService` | Services list, vendor detail, customize catalog render from backend; DB-down shows "unavailable" |
| 2. Dashboard | US2 (P1) | `dashboardService` | Tasks/vouchers/saved designs read + write per-user; second user isolated |
| 3. Blog & social | US3 (P2) | `blogService`, `socialService`, `followsService` | Feed public; authoring/like/comment/follow authenticated; cross-user edit refused |
| 4. Chat history | US4 (P2) | `chatMessageRepository`, `customizeChatRepository`, `FloatingChat.tsx` inline queries | History persists across reload; AI reply path unchanged |
| 5. Admin + analytics | US5 (P3) | `adminService`, `analyticsService`, `profileService` cross-user reads | Every admin panel served by backend; non-admin refused server-side |

Slice 5 lands last because it has the broadest write scope and reuses the
authorization primitives proven by slices 2–4.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Endpoint-class-specific auth gating instead of the constitution's global `ENABLE_AUTH` switch | User-scoped and admin data cannot be served to anonymous callers under any flag value; honoring `ENABLE_AUTH=false` literally on `/api/v1/me/*` would expose every user's private planning data | A single global flag either breaks the existing open try-on endpoints (Principle I contract break) or opens private data (FR-004/FR-009 violation). Per-class gating is the only option that preserves both, and it only ever restricts access |
| Service-role Supabase credential present in the backend | Admin cross-user operations (US5) and analytics aggregation exceed what the caller's JWT can do under current RLS; the current frontend relies on admin RLS override policies that this migration must not weaken | Using only the caller JWT would force keeping broad admin RLS override policies as the sole control, which FR-009 forbids as the *only* enforcement point. Service-role use is confined to `repositories/admin.py` and `repositories/analytics.py`, each call justified in a comment per Principle II |
| Backend scaffolding included in a "routing" feature | `LOMAR_backend/` has no application code in this tree; no data endpoint can exist without a host application, Dockerfile, and deploy path | Assuming the service exists elsewhere would produce a plan that cannot be executed here. Scaffolding is bounded to reproducing the five documented endpoints plus app skeleton |

## Post-Design Constitution Re-Check

To be completed after `/speckit.tasks`, before implementation. Confirm:

- [ ] No new response shape forces a frontend rendering rewrite (Principle I)
- [ ] Every service-role call site carries a justification comment (II)
- [ ] No in-process caches or request-scoped globals introduced (III)
- [ ] CORS allowlist explicit; `SUPABASE_JWT_SECRET` sourced from Secret
      Manager, never `--set-env-vars` (IV)
- [ ] Every endpoint has a timeout and a mapped failure status (V)
- [ ] Every endpoint has a contract test including an authorization negative (VI)
