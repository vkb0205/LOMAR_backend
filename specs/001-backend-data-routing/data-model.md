# Data model: backend-routed application data

The authoritative schema is documented in
`LOMAR_frontend/docs/DATA_Schema.md` and typed in
`LOMAR_frontend/src/shared/types/database.ts`.

## Active ownership model

| Tables | Visibility and ownership |
|---|---|
| `profiles` | Caller-owned profile fields; admins manage application roles |
| `vendors`, `services` | Active rows are public; vendor owners and admins manage writes |
| `posts`, `post_comments`, `post_likes` | Published content is public; mutations are caller-owned |
| `journey_tasks`, `vouchers` | Shared definitions; managed by admins |
| `user_journey_tasks`, `user_vouchers`, `user_favorite_services` | Restricted to `auth.uid()` |
| `chat_threads`, `chat_messages` | Restricted to the owning authenticated user |
| `service_requests` | Customer and vendor-party access; admin oversight |
| `analytics_page_views` | Raw events are private; aggregate RPC is admin-only |
| `wedding_plans`, `wedding_plan_items`, `user_plan_items` | Plan-owner access |
| `bi_agent_definitions`, `bi_agent_runs`, `bi_activities`, `bi_recommendations`, `bi_reports` | Vendor/admin BI access |

## Transport aggregates

- Catalog customization contains services and vendors. Images use
  `services.thumbnail_url`.
- Dashboard data contains tasks and vouchers.
- Blog feed data contains author information, comment/like counts, and caller
  like state.
- Chat thread creation accepts vendor and service context, not design-project
  context.
- Admin metrics exclude reviews and AI generations.

## Invariants

1. Owner identifiers are derived from the verified JWT.
2. RLS and table privileges both enforce the public/authenticated boundary.
3. Inaccessible owner-scoped resources are masked as `404`.
4. Application authorization uses `profiles.role`, not user-editable metadata.
5. Composite-key writes are idempotent.
6. Database and provider details do not appear in public error bodies.

## Removed schema

Migration `20260905110138_simplify_schema.sql` removes
`ai_design_assets`, `ai_design_generations`, `ai_design_projects`,
`post_tags`, `tags`, `service_images`, `reviews`, and `follows`, plus both
surviving `design_project_id` columns. Application code must not query or
serialize those objects.
