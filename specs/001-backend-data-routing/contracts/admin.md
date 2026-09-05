# Admin and analytics contracts

Every `/api/v1/admin/*` endpoint requires a fresh authoritative
`profiles.role = 'admin'` check.

`GET /api/v1/admin/metrics` returns counts for users, vendors, pending vendors,
services, posts, hidden posts, flagged comments, service requests, and new
service requests.

Admin CRUD covers profiles, vendors, services, posts, comments, journey tasks,
vouchers, and service requests. Review and AI-generation endpoints were
removed with their tables.

`GET /api/v1/admin/analytics?days=1..365` returns the website analytics RPC
payload. Public analytics collection remains available through:

- `POST /api/v1/analytics/page-views`
- `POST /api/v1/analytics/page-views/{viewId}/engagement`

Anonymous admin requests return `401`; authenticated non-admin requests return
`403`.
