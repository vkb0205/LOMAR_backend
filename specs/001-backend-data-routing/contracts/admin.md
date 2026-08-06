# Admin + analytics contracts (US5, P3)

Replaces: `adminService.ts`, `analyticsService.ts`, and any cross-user reads
left in `profileService.ts`. Every endpoint independently verifies
`profiles.role == 'admin'` for the caller (FR-005) — never trusts the admin
UI to have already checked.

## `GET /api/v1/admin/metrics`

Returns `PlatformMetrics` (users, vendors, vendorsPending, services, posts,
postsHidden, commentsFlagged, reviewsFlagged, leads, leadsNew, generations,
generationsFailed) exactly as `fetchPlatformMetrics()` computed it.

## `GET /api/v1/admin/profiles?search=<term>`

Same search semantics as `fetchProfiles` (`ilike` across
name/username/email).

## `PUT /api/v1/admin/profiles/{id}/role`

Body: `{ "role": "customer" | "vendor_admin" | "admin" }`.

## `DELETE /api/v1/admin/profiles/{id}`

## `GET /api/v1/admin/vendors` / `PUT /api/v1/admin/vendors/{id}/status` / `DELETE /api/v1/admin/vendors/{id}`

Body for status: `{ "status": "draft" | "active" | "suspended" }`.

## `GET /api/v1/admin/services` / `DELETE /api/v1/admin/services/{id}`

## `GET /api/v1/admin/posts` / `DELETE /api/v1/admin/posts/{id}`

## `GET /api/v1/admin/comments` / `DELETE /api/v1/admin/comments/{id}`

## `GET /api/v1/admin/reviews` / `DELETE /api/v1/admin/reviews/{id}`

## `GET /api/v1/admin/journey-tasks` / `POST` / `PUT /{id}` / `DELETE /{id}`

Bodies validated by the same rules currently in
`parseJourneyTaskInsert`/`parseJourneyTaskUpdate` (moved server-side).

## `GET /api/v1/admin/vouchers` / `POST` / `PUT /{id}` / `DELETE /{id}`

Bodies validated by the same rules currently in
`parseVoucherInsert`/`parseVoucherUpdate` (moved server-side).

## `GET /api/v1/admin/service-requests` / `PUT /{id}/status`

## `GET /api/v1/admin/generations`

Read-only view over `ai_design_generations` for moderation.

## `GET /api/v1/admin/analytics?days=<n>`

Calls `get_admin_website_analytics(p_days)` via the service-role path
(R2/R4). `days` bounded (e.g. 1–365); out-of-range → `422`.

**Response 200**: the same `WebsiteAnalytics` shape `fetchWebsiteAnalytics`
already returns.

## Public analytics tracking (unauthenticated, listed here for completeness)

## `POST /api/v1/analytics/page-views`

Body matches `record_page_view`'s current RPC parameters. Callable
anonymously (visitor tracking); backend attaches `user_id` from JWT only when
a session is present, never accepts a client-supplied `user_id`.

## `POST /api/v1/analytics/page-views/{viewId}/engagement`

Body matches `record_page_engagement`'s current RPC parameters.

## Authorization summary

| Endpoint group | Non-admin authenticated caller | Anonymous caller |
|---|---|---|
| Any `/api/v1/admin/*` | `403 forbidden` | `401 unauthenticated` |
| `/api/v1/analytics/page-views*` | `200` (attributed to caller) | `200` (anonymous) |
