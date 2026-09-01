# Feature Specification: User Wedding-Plan Acceptance & Persistence

**Feature Branch**: `003-user-plan-acceptance`

**Created**: 2026-09-01

**Status**: Draft

**Input**: "The chatbot supports users discovering and planning their wedding preparation. During chat, when the couple agrees with the agent's proposal, they hit an Accept action and the DB records their choice, grouped by category. The recorded choices form the user's plan; only accepted items should surface."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A couple accepts the agent's proposed item (Priority: P1)

While consulting on a logged-in surface, the agent proposes catalog options (services and/or curated wedding plans) rendered as cards. Each card carries an Accept action. When the couple accepts a card, the system persists that choice to the user's plan and marks it `accepted`.

**Why this priority**: Persisting an explicit user decision is the core capability this feature adds; everything else (recall, grouping, dashboard) depends on it.

**Independent Test**: With an authenticated consult session and a live catalog, accept a suggested service card in the chat UI. The choice is recorded under that user (and only that user) with `status = 'accepted'` and its `category` derived from the service.

**Acceptance Scenarios**:

1. **Given** an authenticated user viewing a suggested service card, **When** they trigger Accept, **Then** the choice is upserted under `(user_id, service_id)` with `status = 'accepted'` and the accept timestamp is set.
2. **Given** the same user accepts the same item again, **When** they re-accept, **Then** no duplicate row is created; the existing row's status/timestamp is updated (idempotent).
3. **Given** a user accepts an item, **When** another user queries, **Then** only the owner sees it (RLS `auth.uid() = user_id`).
4. **Given** an anonymous (unauthenticated) consult, **When** the user tries to accept, **Then** the endpoint returns `401` and no choice is persisted.

### User Story 2 - The agent recalls what the user has already decided (Priority: P1)

When the consult request carries a valid JWT, the agent is told the user's accepted-plan summary so it can acknowledge existing choices ("bạn đã chọn xong 3/6 hạng mục…") and avoid re-suggesting what is already locked in.

**Why this priority**: This is the "agent checks relevant info about users" requirement — the accepted store becomes decision context for guidance.

**Independent Test**: With an authenticated consult and a user who has accepted one venue item, start a new consult asking "mình còn thiếu gì?". The reply references the existing accepted choice without re-searching for it.

**Acceptance Scenarios**:

1. **Given** an authenticated consult whose user has accepted items, **When** they ask what remains, **Then** the agent reasons from the accepted-plan context (categories + counts) rather than only from conversation memory.
2. **Given** a `get_user_plan` tool invoked, **When** it reads the accepted view, **Then** it returns only `accepted` rows grouped by `category`, allowlisted, with no PII.
3. **Given** a user with no accepted items, **When** the agent is asked about their plan, **Then** it reports an empty/simple state honestly rather than inventing choices.

### User Story 3 - Accepted choices are exposed as a filtered view (Priority: P2)

A persistent view exposes only `accepted` choices, grouped by `category`, as the canonical "user plan" read path shared by the agent and (later) the dashboard.

**Why this priority**: This is the "view that filters out the status/flags" need and is the stable contract downstream consumers build on.

**Independent Test**: After accepting items across two categories, query the view scoped to the user. Only accepted items appear, grouped by their derived `category`.

**Acceptance Scenarios**:

1. **Given** a user with `proposed`/`declined`/`removed` and `accepted` items, **When** the view is queried, **Then** only `accepted` rows are returned.
2. **Given** an accepted service item, **When** the view is queried, **Then** `category` equals the service's `services.category` value.
3. **Given** an accepted whole-plan item, **When** the view is queried, **Then** `category` falls back to the plan's `style` (plans have no single service category).

---

### Edge Cases

- What if the accepted reference is `service_id` *and* `plan_id` on the same row? Rejected structurally by a `CHECK` constraint (exactly one of `service_id`/`plan_id` is set per `item_type`).
- What if a vendor is later removed or a service is deactivated? `services` uses `on delete cascade`; the view `LEFT JOIN` yields a row with `NULL` service fields rather than dropping the user's accepted decision. The agent omits card rendering for missing/null `id` (consistent with existing card collection).
- What if a plan becomes non-`active`? Same behavior as above: the user's accepted row survives with null plan fields.
- What if two item types share an id? `service_id` and `plan_id` are separate UUID columns under distinct partial unique indexes, so no collision is possible.
- What if the couple accepts an item, then declines later? Status transitions in place (`accepted` → `declined`), `accepted_at` is recomputed/cleared as appropriate; the view excludes it immediately.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST store per-user accepted planning choices in a new `user_plan_items` table, one row per `(user, item)`, with `user_id` always forced from the verified JWT.
- **FR-002**: Each `user_plan_items` row MUST reference exactly one item, either a catalog `service` (`service_id`) or a `wedding_plans` row (`plan_id`), enforced by `item_type` + `CHECK`.
- **FR-003**: Each row MUST carry a mutable `status` drawn from `proposed` / `accepted` / `declined` / `removed`, and an `accepted_at` timestamp set on acceptance.
- **FR-004**: Re-accepting the same item MUST be idempotent (upsert on a partial unique index), never creating duplicate rows.
- **FR-005**: The system MUST expose a security-invoker view `v_user_accepted_plan` that returns only `status = 'accepted'` rows, grouped by `category`, where service `category` is derived from `services.category` and plan `category` falls back to the plan's `style`.
- **FR-006**: RLS on `user_plan_items` MUST follow the existing owner pattern (`auth.uid() = user_id` for select/insert/update/delete); the view MUST inherit RLS (no bypass).
- **FR-007**: The system MUST provide an authenticated endpoint to accept/decline/remove an item (`PUT /api/v1/me/plan-items/{itemType}/{itemId}`), returning `401` for anonymous callers and `422` for invalid statuses.
- **FR-008**: When the consult request carries a valid JWT, the consultant runtime MUST inject the user's accepted-plan summary (categories + counts, no PII) as extra context.
- **FR-009**: The chatbot MUST expose a read-only `get_user_plan` tool that queries `v_user_accepted_plan` through the caller-scoped client, returns allowlisted fields grouped by category, and supports an optional single-category filter.
- **FR-010**: The agent MUST NOT write user state; all acceptance writes come from the authenticated user's Accept action via the endpoint (Constitution: agent observes, user decides).

### Key Entities

- **User Plan Item**: One user's decision about one item. Attributes: `user_id`, `item_type` (`service`|`plan`), `service_id?`, `plan_id?`, `status`, `unit_price?`, `currency`, `source_thread_id?`, `accepted_at`, timestamps. Public when the viewer is the owner.
- **User Accepted Plan (view)**: `user_id`, `category`, `status`, `item_type`, `service_id`, `service_name`, `service_price`, `plan_id`, `plan_name`, `accepted_at` — accepted only.
- **Relation to existing entities**: `user_plan_items.user_id → profiles.id`, `service_id → services.id`, `plan_id → wedding_plans.id`, `source_thread_id → chat_threads.id`. Reuses the existing RLS owner pattern from `user_journey_tasks`.

## Success Criteria *(mandatory)*

- **SC-001**: Accepted items are persisted idempotently and privately per user (owner-scoped RLS verified by contract tests).
- **SC-002**: The view returns only accepted items, correctly grouped by derived `category`.
- **SC-003**: An authenticated agent turn reflects the user's accepted choices (summary context present; no re-search of decided items).
- **SC-004**: All authenticated endpoints and the updated consult contract pass contract tests with the AI provider mocked and no live network or production data.
- **SC-005**: The agent exposes only allowlisted, non-PII accepted-plan fields; no `vendors.email/phone/owner_id` leaks.

## Assumptions

- Persisting a user plan requires an authenticated consult session; anonymous chat can browse and propose but Accept prompts login.
- Category is canonical on `services.category`; `user_plan_items` does not duplicate it (join is the source). Whole-plan items use `wedding_plans.style` as a fallback grouping key.
- The dashboard does not change in this feature; exposing the accepted plan on it is a later extension of the same view.
- The existing `user_journey_tasks` checklist-progress contract is unchanged; user-plan choices are a separate concern.
- The chatbot agent package lives in the sibling `agents/chatbot`; backend HTTP stays in `app/routers/`; migration lives in `LOMAR/supabase/migrations/`.

## Deferred / Future Work

- Dashboard surface showing the accepted plan grouped by category.
- Swap/customize: replacing an accepted service within a category.
- Undo/version history of acceptance changes (currently history is minimal via in-place status updates).
