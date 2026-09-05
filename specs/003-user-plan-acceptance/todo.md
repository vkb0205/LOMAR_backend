# Task List: User Wedding-Plan Acceptance & Persistence

**Feature**: `003-user-plan-acceptance` | **Spec**: [spec.md](./spec.md)

## High priority — core implementation

- [ ] **DB migration** — create `user_plan_items` table (owner RLS, `CHECK` service/plan exclusivity, partial unique indexes for idempotent upsert) + `v_user_accepted_plan` security-invoker view (filter `status = 'accepted'`, derive `category` from `services.category` / `wedding_plans.style`) + supporting indexes.
- [ ] **Backend schemas** — request/response models for accept/decline/remove a plan item (`itemType`, `itemId`, `status`).
- [ ] **Backend repository** — upsert a plan item (last-write-wins) + read the user's accepted plan through the view (owner-scoped, caller client).
- [ ] **Backend route** — authenticated `PUT /api/v1/me/plan-items/{itemType}/{itemId}` (`401` anonymous, `422` invalid status, `404`/`422` unknown item).
- [ ] **Backend consult context** — when a consult request carries a valid JWT, inject the user's accepted-plan summary (categories + counts, no PII) as extra context.
- [ ] **Agent tool** — read-only `get_user_plan` tool (query `v_user_accepted_plan` through caller client, allowlisted fields, grouped by category, optional single-category filter) + register in `TOOL_SPECS`/`_DISPATCH` + prompt guidance (agent observes, user decides).

## Medium priority — tests

- [ ] **Contract tests** — accept endpoint (200 idempotent, 401 anonymous, 422 invalid status); owner scoping (user B cannot see user A); consult context injected only when authenticated.
- [ ] **Agent unit tests** — `get_user_plan` allowlist projection, category grouping, empty/accepted filtering against `FakeSupabase`.

## Low priority — docs

- [ ] Update `docs/data_schema.md`, `docs/ai-agent.md`, `README.md` for feature 003.

## Verification

- [ ] Run full pytest suite and fix regressions.
