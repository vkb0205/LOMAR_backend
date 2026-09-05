# Dashboard contracts

All dashboard endpoints require a customer session. Owner identity always
comes from the verified JWT.

## `GET /api/v1/me/dashboard`

Returns `{ "tasks": [...], "vouchers": [...] }`. Saved AI designs are not
part of the response because the AI-design workspace tables were removed.

## `PUT /api/v1/me/journey-tasks/{taskId}`

Accepts `{ "status": "pending|completed" }` and upserts on
`(user_id, task_id)`. The backend maintains completion timestamps.

## `PUT /api/v1/me/vouchers/{voucherId}`

Accepts `{ "status": "locked|unlocked" }` and upserts on
`(user_id, voucher_id)`. Unknown targets return `404`; invalid states return
`422`.
