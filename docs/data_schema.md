# LOMAR Data Schema (redesigned)

Source of truth: existing Supabase project. This document describes the **target**
schema after simplification. It is not a raw DDL dump — it records the logical
model, the relationships between tables, and the access rules, so engineers can
reason about the data without 500 lines of repetition.

- **Tables: 23 → 15**
- Features removed (to be redesigned later): `follows`, `reviews`, `tags`,
  `post_tags`, `service_images`, and the AI-design set
  (`ai_design_projects`, `ai_design_generations`, `ai_design_assets`).

---

## Shared conventions

Every table below carries these columns *unless noted* (omitted for brevity):

- `id uuid primary key` — identity
- `created_at timestamptz` — server-set
- `updated_at timestamptz` — server-set (mutable tables only)

Conventions in the schema:

- Every `*_id` column is a **foreign key** to the table named by its prefix
  (e.g. `vendor_id → vendors.id`).
- Status/role/type values are **enumerated** — see [Enums](#enums) — never
  free-form `text`.
- Owner columns (`user_id`) always come from the verified JWT, never from a
  request body.

---

## Logical groups

| Group | Tables | Why these group together |
|---|---|---|
| Identity | `profiles` | Single user table; role is the authz source |
| Catalog | `vendors`, `services`, `user_favorite_services`, `wedding_plans`, `wedding_plan_items` | Vendors sell services; users save favorites; plans bundle services into curated offers |
| User plan | `user_plan_items`, `v_user_accepted_plan` (view) | Per-user wedding-plan decisions; accepted-only read path |
| Content (blog) | `posts`, `post_comments`, `post_likes` | Author → post → comments/likes |
| Journey & vouchers | `journey_tasks`, `user_journey_tasks`, `vouchers`, `user_vouchers` | Shared definitions + per-user state |
| Conversation | `chat_threads`, `chat_messages` | 1:n threaded history |
| Sales/leads | `service_requests` | Request a vendor service/budget/date |
| Analytics | `analytics_page_views` | Anonymous, privacy-minimal events |

---

## Tables

### Identity

#### `profiles`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | = `auth.users.id` |
| `username` | `text?` unique | |
| `full_name` | `text?` | |
| `email` | `text?` | |
| `avatar_url` | `text?` | |
| `role` | `user_role` | `customer` / `vendor_admin` / `admin` |
| `onboarding_status` | `text` | shape pending redesign |

### Catalog

#### `vendors`

| Column | Type | Notes |
|---|---|---|
| `owner_id` | `uuid?` → `profiles.id` | vendor admin account owns this vendor |
| `name` | `text` | |
| `slug` | `text` unique | public URL key |
| `category` | `text` | |
| `description` | `text?` | |
| `address`, `city`, `phone`, `email` | `text?` | |
| `website_url`, `image_url` | `text?` | |
| `rating_avg` | `numeric` | display counter |
| `rating_count` | `int` | display counter |
| `status` | `entity_status` | `active` = public |

#### `services`

| Column | Type | Notes |
|---|---|---|
| `vendor_id` | `uuid` → `vendors.id` | a service belongs to one vendor |
| `category` | `text` | mirror of vendor category for catalog filters |
| `name` | `text` | |
| `description` | `text?` | |
| `base_price` | `numeric` | |
| `currency` | `text` | ISO code |
| `thumbnail_url` | `text?` | primary image (child-image table removed) |
| `status` | `entity_status` | `active` = public |

#### `user_favorite_services`

Per-user saved services. Composite `(user_id, service_id)` primary key.

| Column | Type | Notes |
|---|---|---|
| `user_id` | `uuid` PK → `profiles.id` | forced from JWT |
| `service_id` | `uuid` PK → `services.id` | |
| `saved_at` | `timestamptz` | |

#### `wedding_plans`

A curated wedding package bundling catalog services (possibly from different
vendors) into one priced offer. Introduced by feature `002-wedding-plan-chatbot`.

| Column | Type | Notes |
|---|---|---|
| `name` | `text` | short public label |
| `description` | `text?` | short public blurb |
| `style` | `text?` | e.g. classic / minimal / garden (free-text) |
| `min_guests`, `max_guests` | `int` | expected guest-capacity band |
| `min_budget`, `max_budget` | `numeric` | published price band (display) |
| `currency` | `text` | ISO code |
| `cover_image_url` | `text?` | optional primary image |
| `status` | `text` | catalog visibility — `active` = public |

> Published budget is authoritative **display** data; it is not recomputed from
> the items (mirrors `services.base_price`). One plan = many `wedding_plan_items`.

#### `wedding_plan_items`

Line items linking a plan to existing catalog services. Composite ownership:
many items belong to one plan.

| Column | Type | Notes |
|---|---|---|
| `wedding_plan_id` | `uuid` PK? → `wedding_plans.id` | owning plan, `on delete cascade` |
| `service_id` | `uuid` → `services.id` | the bundled catalog service |
| `role` | `text` | venue / catering / photography / attire / … |
| `sort_order` | `int` | display order |
| `quantity` | `int` | default 1 |
| `unit_price` | `numeric` | item contribution (display) |
| `currency` | `text` | ISO code |

A plan item's vendor resolves through `services.vendor_id`; no vendor is
duplicated.

### User plan (feature `003-user-plan-acceptance`)

#### `user_plan_items`

One explicit couple decision about one catalog item (service or whole plan).
Composite-per-item uniqueness: exactly one `service_id` / `plan_id` per
`item_type` (CHECK), with a partial unique index per non-null id column so
re-accepting is idempotent.

| Column | Type | Notes |
|---|---|---|
| `user_id` | `uuid` → `profiles.id` | forced from JWT |
| `item_type` | `text` | `service` / `plan` |
| `service_id` | `uuid?` → `services.id` | `on delete cascade`, `null` when `item_type = 'plan'` |
| `plan_id` | `uuid?` → `wedding_plans.id` | `on delete cascade`, `null` when `item_type = 'service'` |
| `status` | `text` | `proposed` / `accepted` / `declined` / `removed` |
| `unit_price` | `numeric?` | optional snapshot at acceptance |
| `currency` | `text` | ISO code |
| `source_thread_id` | `uuid?` → `chat_threads.id` | optional origin consult thread |
| `accepted_at` | `timestamptz?` | set on `accepted`, cleared on other statuses |
| `created_at`, `updated_at` | `timestamptz` | |

Category is **not** duplicated on the row — it is derived by the view from
`services.category` (or `wedding_plans.style` for whole-plan items).

#### `v_user_accepted_plan` (view)

A `SECURITY INVOKER` view returning **only** `status = 'accepted'` rows, grouped
by the derived `category`. Columns: `user_id`, `item_type`, `category`,
`service_id`, `service_name`, `service_price`, `plan_id`, `plan_name`,
`accepted_at`. Because it is security-invoker it inherits the caller's RLS, so
it never grants read of another user's row. Uses `LEFT JOIN` so a removed
vendor/service/plan yields `NULL` display fields instead of dropping the user's
accepted decision.

### Content (blog)

#### `posts`

| Column | Type | Notes |
|---|---|---|
| `user_id` | `uuid` → `profiles.id` | author, forced from JWT |
| `title` | `text?` | |
| `content` | `text` | |
| `cover_image_url` | `text?` | |
| `views_count` | `int` | |
| `status` | `publication_status` | `draft` / `published` / `archived` |

#### `post_comments`

| Column | Type | Notes |
|---|---|---|
| `post_id` | `uuid` → `posts.id` | |
| `user_id` | `uuid` → `profiles.id` | author, forced from JWT |
| `parent_comment_id` | `uuid?` → `post_comments.id` | self-FK for threads |
| `content` | `text` | |
| `status` | `moderation_status` | `visible` / `hidden` / `flagged` |

#### `post_likes`

`(post_id, user_id)` composite PK; unlike is a delete. Idempotent.

| Column | Type |
|---|---|
| `post_id` | `uuid` PK → `posts.id` |
| `user_id` | `uuid` PK → `profiles.id` |
| `created_at` | `timestamptz` |

### Journey & vouchers

#### `journey_tasks`

Shared task **definitions** (admin-managed). No per-user columns.

| Column | Type | Notes |
|---|---|---|
| `code` | `text` unique | stable key |
| `name` | `text` | |
| `description` | `text?` | |
| `is_mandatory` | `bool` | |
| `display_order` | `int` | |
| `active` | `bool` | |

#### `user_journey_tasks`

Per-user progress on a task definition. Composite `(user_id, task_id)` PK.

| Column | Type | Notes |
|---|---|---|
| `user_id` | `uuid` PK → `profiles.id` | forced from JWT |
| `task_id` | `uuid` PK → `journey_tasks.id` | |
| `status` | `task_progress` | `pending` / `completed` |
| `completed_at` | `timestamptz?` | |

#### `vouchers`

Shared voucher **definitions**.

| Column | Type | Notes |
|---|---|---|
| `vendor_id` | `uuid?` → `vendors.id` | optional issuer |
| `code` | `text` unique | |
| `title` | `text` | |
| `description` | `text?` | |
| `discount_type` | `text` | e.g. `percent` / `fixed` |
| `discount_value` | `numeric` | |
| `min_order_value` | `numeric?` | |
| `required_task_id` | `uuid?` → `journey_tasks.id` | unlock gate |
| `starts_at`, `expires_at` | `timestamptz?` | |
| `max_redemptions` | `int?` | |
| `active` | `bool` | |

#### `user_vouchers`

Per-user claim state. Composite `(user_id, voucher_id)` PK.

| Column | Type | Notes |
|---|---|---|
| `user_id` | `uuid` PK → `profiles.id` | forced from JWT |
| `voucher_id` | `uuid` PK → `vouchers.id` | |
| `status` | `voucher_claim_status` | `locked` / `unlocked` / `redeemed` |
| `unlocked_at` | `timestamptz?` | |
| `redeemed_at` | `timestamptz?` | |

### Conversation

#### `chat_threads`

| Column | Type | Notes |
|---|---|---|
| `user_id` | `uuid` → `profiles.id` | forced from JWT |
| `title` | `text?` | |
| `context_type` | `chat_context` | `general` / `service` / `vendor` |
| `service_id` | `uuid?` → `services.id` | context target |
| `vendor_id` | `uuid?` → `vendors.id` | context target |

> Removed: `design_project_id` (AI-design tables dropped).

#### `chat_messages`

| Column | Type | Notes |
|---|---|---|
| `thread_id` | `uuid` → `chat_threads.id` | |
| `user_id` | `uuid` → `profiles.id` | author (assistant msgs use system) |
| `role` | `chat_role` | `user` / `assistant` |
| `content` | `text` | |
| `suggested_service_id` | `uuid?` → `services.id` | assistant suggestions |
| `metadata` | `jsonb` | |

Ordering for replay: `created_at ASC, id ASC`.

### Sales/leads

#### `service_requests`

| Column | Type | Notes |
|---|---|---|
| `user_id` | `uuid` → `profiles.id` | requester, forced from JWT |
| `vendor_id` | `uuid` → `vendors.id` | |
| `service_id` | `uuid?` → `services.id` | |
| `event_date` | `date?` | |
| `budget_min`, `budget_max` | `numeric?` | |
| `message` | `text?` | |
| `status` | `request_status` | `pending` / `accepted` / `declined` / `cancelled` |

> Removed: `design_project_id` (AI-design tables dropped).

### Analytics

#### `analytics_page_views`

Privacy-minimal. No IP or raw user-agent stored.

| Column | Type | Notes |
|---|---|---|
| `session_id` | `uuid` | |
| `visitor_id` | `uuid` | |
| `user_id` | `uuid?` → `profiles.id` | derived from JWT when present; never client-supplied |
| `page_path` | `text` | |
| `page_title` | `text?` | |
| `referrer_host` | `text?` | |
| `duration_seconds` | `int` | |
| `max_scroll_percent` | `smallint` | |
| `occurred_at` | `timestamptz` | |

---

## Relationships

```
profiles ──┬─< vendors.owner_id
           ├─< services.vendor_id        (via vendors)
           ├─< user_favorite_services    (user_id, service_id)
           ├─< posts.user_id ──< post_likes / post_comments
           ├─< user_journey_tasks ──< journey_tasks
           ├─< user_vouchers ──< vouchers ──< required_task_id → journey_tasks
           ├─< chat_threads ──< chat_messages
           ├─< user_plan_items ──< services / wedding_plans / chat_threads
           └─< service_requests ──< vendors / services
vendors  ──< services
wedding_plans ──< wedding_plan_items ──> services.id
```

Key FK arcs (all `*_id` columns on the child point to `id` of the parent):

- `vendors.owner_id → profiles.id`
- `services.vendor_id → vendors.id`
- `user_favorite_services(user_id → profiles, service_id → services)`
- `posts.user_id → profiles.id`
- `post_comments(post_id → posts, user_id → profiles, parent_comment_id → post_comments)`
- `post_likes(post_id → posts, user_id → profiles)`
- `user_journey_tasks(user_id → profiles, task_id → journey_tasks)`
- `user_vouchers(user_id → profiles, voucher_id → vouchers)`
- `vouchers(vendor_id → vendors, required_task_id → journey_tasks)`
- `chat_threads(user_id → profiles, service_id → services, vendor_id → vendors)`
- `chat_messages(thread_id → chat_threads, user_id → profiles, suggested_service_id → services)`
- `service_requests(user_id → profiles, vendor_id → vendors, service_id → services)`
- `analytics_page_views.user_id → profiles`
- `user_plan_items(user_id → profiles, service_id → services, plan_id → wedding_plans, source_thread_id → chat_threads)`

---

## Enums

Recommended enumerated types replacing loose `text`. Actual live values must be
confirmed before `ALTER TYPE` (see migration note).

| Enum | Values | Used by |
|---|---|---|
| `user_role` | `customer`, `vendor_admin`, `admin` | `profiles.role` |
| `entity_status` | `active`, `inactive`, `pending` | `vendors.status`, `services.status` |
| `publication_status` | `draft`, `published`, `archived` | `posts.status` |
| `moderation_status` | `visible`, `hidden`, `flagged` | `post_comments.status` |
| `task_progress` | `pending`, `completed` | `user_journey_tasks.status` |
| `voucher_claim_status` | `locked`, `unlocked`, `redeemed` | `user_vouchers.status` |
| `chat_context` | `general`, `service`, `vendor` | `chat_threads.context_type` |
| `chat_role` | `user`, `assistant` | `chat_messages.role` |
| `request_status` | `pending`, `accepted`, `declined`, `cancelled` | `service_requests.status` |
| `plan_item_status` | `proposed`, `accepted`, `declined`, `removed` | `user_plan_items.status` |

---

## Access (RLS) summary

**Default policy on every table:** `ALL … USING is_admin() WITH CHECK is_admin()`
(admin manages all rows). Only the non-default rules are listed.

| Table | Additional policy |
|---|---|
| `profiles` | user `UPDATE` own, `SELECT` own |
| `vendors` | public `SELECT` where `status = 'active'` |
| `services` | public `SELECT` where `status = 'active'` |
| `wedding_plans` | public `SELECT` where `status = 'active'` |
| `wedding_plan_items` | public `SELECT` where owning plan is `active` |
| `posts` | public `SELECT` where `status = 'published'` |
| `user_plan_items` | owner CRUD (`auth.uid() = user_id`), mirrors `user_journey_tasks` |
| `analytics_page_views` | admin `SELECT` only; inserts via `record_page_view` RPC |

---

## Migration summary

One migration drops the removed features and the orphaned references:

1. Drop orphaned FK columns on surviving tables:
   - `chat_threads.design_project_id`
   - `service_requests.design_project_id`
2. Drop removed tables in dependency order:
   `ai_design_assets`, `ai_design_generations`, `ai_design_projects`,
   `post_tags`, `tags`, `service_images`, `reviews`, `follows`.
3. (Optional, disabled by default) Convert `text` status/role/type columns to
   the [enums](#enums) — requires confirming live data conforms first.