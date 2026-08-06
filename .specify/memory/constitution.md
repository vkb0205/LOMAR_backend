<!--
SYNC IMPACT REPORT
==================
Version change: (uninitialized template) → 1.0.0
Rationale: First ratification. Template placeholders replaced with concrete
principles derived from the existing LOMAR repository (frontend contract,
Supabase schema, Cloud Run deployment workflow).

Modified principles:
  - [PRINCIPLE_1_NAME] → I. Frontend Contract Is Law
  - [PRINCIPLE_2_NAME] → II. Supabase Is The System Of Record
  - [PRINCIPLE_3_NAME] → III. Stateless, Container-Native Service
  - [PRINCIPLE_4_NAME] → IV. Secure By Default
  - [PRINCIPLE_5_NAME] → V. Observability And Graceful Degradation
  - [PRINCIPLE_6_NAME] → VI. Test The Contract, Not The Model (added)

Added sections:
  - Technology & Integration Constraints (was [SECTION_2_NAME])
  - Development Workflow & Quality Gates (was [SECTION_3_NAME])

Removed sections: none

Templates requiring updates:
  ✅ .specify/templates/plan-template.md — no change needed; "Constitution
     Check" gate resolves against this file dynamically.
  ✅ .specify/templates/spec-template.md — no change needed; no mandatory
     sections added or removed by this constitution.
  ✅ .specify/templates/tasks-template.md — no change needed; principle-driven
     task types (contract tests, observability, deployment) already fit the
     existing phase structure.
  ✅ .claude/skills/speckit-*/SKILL.md — reviewed; no agent-specific stale
     references introduced by this amendment.
  ⚠ README.md (LOMAR_backend) — does not exist yet; create when the service
     is scaffolded and link back to this constitution.

Deferred TODOs:
  - TODO(RATIFICATION_DATE): resolved as 2026-08-06, the date this
    constitution was first filled in. Amend if the team recognizes an earlier
    adoption date.
-->

# LOMAR Backend Constitution

The LOMAR backend is the server-side service for the LOMAR wedding-service
ecosystem (Phố Hạnh Phúc Hồ Văn Huê). It lives in its own repository directory,
`LOMAR_backend/`, and serves the React/Vite frontend in `LOMAR/`.

## Core Principles

### I. Frontend Contract Is Law

The frontend is already written against a specific HTTP contract. The backend
MUST satisfy that contract rather than force frontend rewrites.

- The service MUST expose, at minimum, the endpoints the frontend already
  calls: `GET /health`, `GET /proxy-image?url=<encoded>`,
  `POST /test-try-on`, `POST /test-try-on-upload`, and `POST /consult`.
- `POST /test-try-on-upload` MUST accept `multipart/form-data` with fields
  `body_image`, `garment_image`, `category`, and `prompt`.
- Try-on responses MUST include an image URL readable as `imageUrl`,
  `image_url`, `output.imageUrl`, or `output.image_url`, and SHOULD include a
  human-readable `message`.
- `POST /consult` MUST accept `{ "message": string }` and return the reply
  shape the frontend's `ConsultResponse` expects.
- Any breaking change to a request or response shape MUST ship with a
  coordinated change in `LOMAR/src/features/**/services/` and
  `LOMAR/src/shared/api/`, referenced in the same pull request.

**Rationale**: The frontend deploys independently to GitHub Pages and cannot be
hot-fixed in lockstep with the backend. Contract drift breaks production users
silently.

### II. Supabase Is The System Of Record

Supabase (PostgreSQL) owns durable application data. The backend MUST NOT
introduce a competing primary datastore.

- Schema changes MUST be expressed as ordered Supabase CLI migrations in
  `LOMAR/supabase/migrations/`, never as ad-hoc SQL run against production.
- The backend MUST respect Row Level Security. Service-role credentials MAY be
  used only for operations that provably cannot be performed with the caller's
  JWT, and each such use MUST be justified in code comments.
- The backend MUST NOT duplicate business entities (vendors, products,
  designs, vouchers, journey tasks) into private tables. Caches are permitted
  only when they are explicitly invalidated and non-authoritative.

**Rationale**: The frontend reads Supabase directly. A second source of truth
would produce two divergent views of the same wedding journey.

### III. Stateless, Container-Native Service

The service MUST be horizontally scalable and disposable.

- No request-scoped state may persist in process memory between requests.
  Session state lives in Supabase or in the client.
- The service MUST bind to `API_HOST`/`API_PORT` (default `0.0.0.0:8080`) and
  MUST NOT hardcode a port.
- All configuration MUST come from environment variables. No secret, project
  ID, model name, or endpoint may be committed to the repository.
- The service MUST start successfully from a clean container with only
  environment variables supplied, and MUST answer `GET /health` without
  requiring any upstream dependency to be reachable.

**Rationale**: Deployment targets Google Cloud Run, which scales to zero and
replaces instances freely.

### IV. Secure By Default

- CORS MUST be restricted to an explicit allowlist of frontend origins,
  configured per environment. Wildcard origins are forbidden in production.
- When `ENABLE_AUTH=true`, protected endpoints MUST verify the Supabase JWT
  supplied as `Authorization: Bearer <token>` and MUST reject invalid or
  expired tokens with `401`. When `ENABLE_AUTH` is false the service MAY run
  open, and endpoints MUST still function for unauthenticated callers.
- `GET /proxy-image` MUST validate and constrain the target URL. It MUST NOT
  be usable as an open forwarder to internal or private-network addresses
  (SSRF), and MUST cap response size and timeout.
- All request payloads MUST be validated with typed models before use.
  Uploaded images MUST be checked for content type and size limits.
- Errors returned to clients MUST NOT leak stack traces, credentials, upstream
  provider messages, or internal hostnames.

**Rationale**: The service is deployed with `--allow-unauthenticated` and calls
a billed AI provider; an unvalidated endpoint is both a security and a cost
incident.

### V. Observability And Graceful Degradation

- Logs MUST be structured and MUST include a correlation identifier per
  request. Logs MUST NOT contain access tokens, API keys, or raw user images.
- Every outbound AI or storage call MUST have an explicit timeout and a
  defined failure path. Failures MUST surface as actionable HTTP status codes,
  not as hangs.
- `GET /health` MUST report liveness cheaply and MUST NOT be gated by auth.
- When the image model is unavailable, the service MUST return a clear error
  the frontend can present to the user rather than an opaque `500`.

**Rationale**: The frontend already renders backend error text to users; poor
error hygiene becomes a visible product defect.

### VI. Test The Contract, Not The Model

- Every endpoint MUST have a contract test asserting status codes, request
  validation, and response shape, with the AI provider mocked.
- Tests MUST NOT depend on live Vertex AI, live network image fetches, or
  production Supabase data.
- Bug fixes MUST add a regression test reproducing the reported failure before
  the fix is merged.
- Generative image quality is explicitly NOT asserted in automated tests; it
  is validated manually.

**Rationale**: Non-deterministic model output cannot anchor a test suite, but
the transport contract around it can and must.

## Technology & Integration Constraints

- **Runtime**: Python with FastAPI, served by an ASGI server, packaged with a
  `Dockerfile` at the backend root. Dependencies pinned in a committed
  requirements or lock file.
- **AI provider**: Google GenAI SDK. Vertex AI mode is the default
  (`GOOGLE_GENAI_USE_VERTEXAI=true`) with API-key mode as fallback. The image
  model is selected by environment variable (currently `NANO_BANANA_MODEL`),
  never hardcoded.
- **Data**: Supabase PostgreSQL. Canonical schema documentation is
  `LOMAR/docs/DATA_Schema.md`; migrations live in `LOMAR/supabase/migrations/`.
- **Deployment**: Google Cloud Run, region `us-central1`, project
  `lomar-500117`, via `.github/workflows/deploy-backend.yml`. That workflow's
  build path MUST point at the real backend directory; the current
  `vton_test_ui/` path is stale and MUST be corrected before the next deploy.
- **Frontend coupling**: In development the frontend proxies `/api/vton/*` to
  this service; in production it calls `VITE_VTON_BACKEND_URL` directly. Both
  paths MUST remain functional.
- **Repository boundary**: Backend code stays in `LOMAR_backend/`. It MUST NOT
  be imported into, or vendored inside, the Vite source tree.

## Development Workflow & Quality Gates

- Work follows the Spec Kit flow: `/speckit-specify` → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-implement`. Each feature gets a numbered
  directory under `specs/`.
- Every implementation plan MUST pass the Constitution Check gate before
  Phase 0 research and again after Phase 1 design. Violations MUST be recorded
  in the plan's Complexity Tracking table with a rejected simpler alternative.
- A change is mergeable only when: contract tests pass, no secrets are added
  to version control, environment variables are documented, and any endpoint
  change is reflected in the frontend service layer.
- Endpoint additions MUST be documented in the backend `README.md` with method,
  path, request shape, response shape, and auth expectation.
- Complexity MUST be justified. Prefer the smallest change that satisfies the
  spec; new abstractions require a stated second consumer.

## Governance

This constitution supersedes ad-hoc practice for the LOMAR backend. Where this
document and a habit conflict, this document wins.

- **Amendments** MUST be made by editing this file, with a Sync Impact Report
  recorded in the HTML comment at the top, and MUST state the rationale for
  the change.
- **Versioning** follows semantic versioning:
  - MAJOR: a principle is removed or redefined in a backward-incompatible way.
  - MINOR: a principle or section is added, or guidance is materially expanded.
  - PATCH: clarification, wording, or typo fixes with no semantic change.
- **Compliance review**: every pull request MUST be checked against these
  principles. Reviewers MUST reject changes that violate Principles I, II, or
  IV without an explicit, documented exception.
- **Dependent artifacts**: when this constitution changes, the plan, spec, and
  tasks templates under `.specify/templates/` MUST be re-read and updated if
  the change adds or removes mandatory sections or gates.
- **Runtime guidance**: day-to-day development guidance lives in the backend
  `README.md` and in `LOMAR/ARCHITECTURE.md` for the frontend boundary. Those
  documents MUST NOT contradict this constitution.

**Version**: 1.0.0 | **Ratified**: 2026-08-06 | **Last Amended**: 2026-08-06
