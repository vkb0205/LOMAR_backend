# Data Model: Backend-Routed Application Data

## Source of truth

Existing Supabase schema represented by
[`database.ts`](../../../LOMAR/src/shared/types/database.ts). This feature adds
no business tables. Backend schemas validate transport payloads; Supabase
schema remains authoritative for persistence, foreign keys, unique constraints,
and timestamps.

## Visibility and ownership matrix

| Table / RPC | Slice | Read visibility | Write visibility | Ownership / authorization rule |
|---|---|---|---|---|
| `vendors` | Catalog; Admin | Public active catalog; full admin list | Admin | Public endpoint filters to catalog-visible status; admin endpoint may see/update all |
| `services` | Catalog; Admin | Public catalog/customize; full admin list | Admin | Public endpoint returns catalog-visible services; service belongs to `vendors` |
| `service_images` | Catalog; Admin | Public with service catalog; admin | Admin | Exposed only through existing service/vendor response context; `service_id` FK required |
| `profiles` | Social; Admin | Public author display fields only; own profile; admin | Own profile fields; admin role/delete | Backend never exposes private fields to public; admin role check reads caller's profile |
| `posts` | Social; Admin | Public published/visible feed | Authenticated own create/update/delete; admin moderation | `user_id` forced from JWT; editing another owner returns `404` |
| `tags` | Social; Admin | Public feed metadata | Admin / controlled post-author association | Tag IDs validated before association |
| `post_tags` | Social; Admin | Public through feed | Post owner/admin | Post ownership checked before mutation |
| `post_comments` | Social; Admin | Public visible comments | Authenticated own create/update/delete; admin moderation | `user_id` forced from JWT; non-owner target masked as `404` |
| `post_likes` | Social | Public aggregate/current-user state | Authenticated current user only | Composite identity `(post_id, user_id)`; like/unlike idempotent |
| `follows` | Social | Public relationship/counts as current UI needs | Authenticated current follower only | `follower_id` forced from JWT; target must exist; no self-follow unless current behavior permits |
| `journey_tasks` | Dashboard; Admin | Authenticated dashboard active definitions; admin full | Admin | Shared definitions; no user-supplied owner |
| `user_journey_tasks` | Dashboard | Current user only | Current user only | `user_id` forced from JWT; upsert `(user_id, task_id)`; last write wins |
| `vouchers` | Dashboard; Admin | Authenticated dashboard available definitions; admin full | Admin | Shared definitions; claim state lives separately |
| `user_vouchers` | Dashboard | Current user only | Current user only; admin support if current admin UI needs it | `user_id` forced from JWT; upsert `(user_id, voucher_id)`; no duplicate claims |
| `ai_design_projects` | Dashboard; Chat; Admin | Current user only; admin where moderation panel requires | Current user only; admin as explicit admin action | `user_id` forced from JWT; project ID lookup owner-scoped |
| `ai_design_generations` | Chat; Admin | Current user project only; admin | Current user / existing AI flow; admin moderation | Project and generation ownership must agree |
| `ai_design_assets` | Chat; Admin | Current user project only; admin | Current user / existing AI flow; admin | Project, generation, and user FKs validated |
| `chat_threads` | Chat | Current user only | Current user only | `user_id` forced from JWT; guessed foreign IDs return `404` |
| `chat_messages` | Chat | Current user's thread only | Current user thread; assistant message server-created | Client cannot impersonate another user or inject assistant identity outside validated flow |
| `service_requests` | Dashboard/Admin | Current user own requests; admin full | Current user create; admin status/moderation | Vendor/service/design-project FKs validated; user forced from JWT |
| `reviews` | Social/Admin | Public approved/visible reviews; admin full; own pending state | Current user own create/update; admin moderation | Target vendor/service existence checked; non-owner update masked |
| `user_favorite_services` | Catalog/Dashboard/Admin if exposed | Current user only | Current user only | `user_id` forced from JWT; composite identity idempotent |
| `analytics_page_views` | Analytics | Admin aggregates only | Public visitor tracking RPC | Raw event rows never public; visitor/session payload validated and size-limited |
| `get_admin_website_analytics` | Admin/Analytics | Admin only | N/A | Service-role/RPC path justified; `p_days` bounded |
| `record_page_view` | Analytics | N/A | Public tracking RPC | Backend supplies authenticated user ID when available; never accepts arbitrary user ID |
| `record_page_engagement` | Analytics | N/A | Public tracking RPC | Event ID/session identity validated; no cross-user mutation |
| `is_admin` | Auth/Admin | Backend-internal only | N/A | Not exposed as a public endpoint; backend checks `profiles.role` directly for stable authorization |

## Transport aggregates

Backend aggregates preserve current frontend service outputs. They are not
new persistent entities.

### Catalog aggregate

- `VendorCard`: vendor row fields consumed by `VendorCard` plus its public
  service summary.
- `VendorDetail`: vendor row, associated service rows, service-image rows,
  review data where current detail UI requests it.
- `CustomizeCatalog`: service rows, image rows, vendor rows matching current
  `CustomizeCatalog` type.

### Dashboard aggregate

`DashboardData` contains:

- `tasks`: `taskId`, `name`, `isMandatory`, normalized `pending|completed`
- `vouchers`: `voucherId`, `title`, `discountValue`, normalized status,
  `requiredTaskId`
- `savedDesigns`: `id`, `title`, `category`, `status`, `created_at`

Backend performs the joins and status normalization currently in
`dashboardService.ts`; frontend receives the same shape and renders it.

### Social aggregate

`BlogFeed` contains posts with public author display info, tag metadata,
visible comments, like count/current-user like state when authenticated, and
follow state/counts where requested by the current UI. Mutation responses
return the affected post/comment/relationship in the shape existing hooks
need, or a stable `{ ok: true }` body when callers currently only await
completion.

### Chat aggregate

`ChatThread` contains thread metadata plus ordered `ChatMessage` rows. Message
history always orders by `created_at ASC, id ASC` for deterministic replay.
Assistant messages are persisted by the backend after the existing AI reply
is produced; AI generation behavior itself is unchanged.

### Admin aggregate

Admin panel responses preserve current service return values: row arrays,
counts/metrics, generation records, and analytics aggregate JSON. Backend
normalizes only transport errors and authorization; it does not silently
change admin field names.

## Invariants

1. **Identity**: Every owner column is derived from verified JWT `sub`, never
   accepted from a request body or trusted URL alone.
2. **Foreign keys**: Referenced vendor/service/post/task/voucher/project/thread
   IDs must exist and be accessible under the caller's authorization context
   before mutation.
3. **Privacy**: Owner-scoped resource lookup filters by both ID and caller ID
   in one query. No existence leak: wrong-owner and absent rows both return
   `404/not_found`.
4. **Role**: Admin operations require a fresh backend lookup of
   `profiles.role == 'admin'`; UI guards are not security controls.
5. **Idempotency**: Journey task and voucher writes use existing composite
   unique constraints with Postgres upsert; later committed write wins.
6. **Status**: Server validates enum-like statuses (`pending/completed`,
   `locked/unlocked`, moderation statuses) before storage.
7. **Timestamps**: Server/database sets `created_at`, `updated_at`,
   `completed_at`, `unlocked_at`; clients cannot backdate protected events.
8. **Pagination/limits**: Public feeds and admin lists use bounded page size;
   request limits are explicit even if current UI initially requests one page.
9. **Error privacy**: Database/provider details never enter response bodies;
   correlation ID allows operators to locate the internal failure.
10. **Analytics attribution**: Backend may derive `user_id` from JWT, but
    never trusts a client-supplied user ID for tracking events.

## Schema/migration impact

Expected: **no migration**. Existing unique constraints and foreign keys
support required behavior. Before implementation, verify constraints in the
current Supabase project/schema. If a required uniqueness or FK constraint is
missing, add one ordered migration under `LOMAR/supabase/migrations/` and
update generated frontend types; do not create backend-only shadow tables.
