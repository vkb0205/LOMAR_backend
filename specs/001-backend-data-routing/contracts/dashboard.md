# Dashboard contracts (US2, P1)

Replaces: `dashboardService.ts`. All endpoints in this slice are
**authenticated**; every row is scoped to the caller's `user_id`, derived
from the verified JWT — never from the request.

## `GET /api/v1/me/dashboard`

Returns the same aggregate `fetchDashboardData(userId)` produced.

**Response 200**
```json
{
  "tasks": [
    { "taskId": "uuid", "name": "string", "isMandatory": true, "status": "pending" }
  ],
  "vouchers": [
    {
      "voucherId": "uuid",
      "title": "string",
      "discountValue": "string",
      "status": "locked",
      "requiredTaskId": "uuid"
    }
  ],
  "savedDesigns": [
    { "id": "uuid", "title": "string", "category": "string", "status": "string", "created_at": "iso" }
  ]
}
```

**Response 401**: no/invalid session.

## `PUT /api/v1/me/journey-tasks/{taskId}`

Replaces `updateUserJourneyTaskStatus`. Body:
```json
{ "status": "completed" }
```
`status` ∈ `pending | completed`. Server sets `completed_at` when
`completed`, clears it otherwise, and upserts on `(user_id, task_id)` —
concurrent devices resolve to whichever write commits last (edge case in
spec).

**Response 200**: `{ "ok": true }`
**Response 422**: unknown `status` value or missing `taskId`.
**Response 404**: `taskId` does not reference an active journey task.

## `PUT /api/v1/me/vouchers/{voucherId}`

Replaces `updateUserVoucherStatus`. Body:
```json
{ "status": "unlocked" }
```
`status` ∈ `locked | unlocked`. Server sets `unlocked_at` when `unlocked`,
upserts on `(user_id, voucher_id)` — no duplicate claim rows regardless of
how many near-simultaneous requests arrive.

**Response 200**: `{ "ok": true }`
**Response 422**: unknown `status` value.
**Response 404**: `voucherId` does not reference an existing voucher.

## Notes

- `celebrateTaskCompletion()` (confetti) stays entirely client-side; it is a
  UI effect, not a data operation, and is out of scope for backend routing.
- Session-expired-mid-action edge case: any of the two `PUT` endpoints called
  with an expired token returns `401`; frontend must prompt re-auth rather
  than silently dropping the change (spec edge case, already required
  behavior of the shared auth-error handling used across all authenticated
  endpoints).
