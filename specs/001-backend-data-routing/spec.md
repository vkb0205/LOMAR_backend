# Feature Specification: Backend-Routed Application Data

**Feature Branch**: `001-backend-data-routing`

**Created**: 2026-08-06

**Status**: Draft

**Input**: User description: "I want to route the backend to the supabase DB given in the LOMAR frontend, move the logic to the backend and remove that logic from the frontend."

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
-->

### User Story 1 - Visitors browse the catalog through the backend (Priority: P1)

A visitor opens the vendor/services catalog, a vendor detail page, or the
customization catalog. Today the frontend queries the wedding-service
database directly with a public key; going forward, the frontend asks the
backend for this catalog data, and the backend is the only component that
talks to the database.

**Why this priority**: Catalog browsing is the highest-traffic, most public
part of the product and touches the most data domains (vendors, services,
service images). It establishes the read-path pattern every other story
reuses.

**Independent Test**: With the frontend's direct database access removed,
load the services list, a single vendor's detail page, and the customization
catalog. All three must render the same data as before, sourced only through
backend calls.

**Acceptance Scenarios**:

1. **Given** a visitor with no account, **When** they open the services
   catalog, **Then** they see the full list of vendors, services, and service
   images, retrieved via the backend rather than a direct database
   connection.
2. **Given** a visitor viewing a specific vendor, **When** the vendor detail
   page loads, **Then** the backend returns that vendor's profile and its
   associated services, and the page renders identically to today's
   behavior.
3. **Given** the database is temporarily unreachable, **When** a visitor
   loads the catalog, **Then** the frontend shows a clear "unavailable" state
   instead of a raw error or blank screen.

---

### User Story 2 - Signed-in users manage their own journey data through the backend (Priority: P1)

A signed-in user opens their dashboard to see their wedding-planning journey
tasks, vouchers, and saved AI design projects, and marks a task complete or
claims a voucher. Today these reads and writes go straight from the browser
to the database using the user's session; going forward, the backend
performs them on the user's behalf while still respecting that only the
signed-in user can see or change their own records.

**Why this priority**: This is the core authenticated experience and the
primary place where per-user data protection matters most (a bug here leaks
or corrupts one user's private planning data).

**Independent Test**: Sign in as a user, load the dashboard, mark a journey
task complete, and claim a voucher. Confirm the dashboard reflects the
change, and confirm a second user's dashboard is unaffected and cannot see
the first user's task/voucher state.

**Acceptance Scenarios**:

1. **Given** a signed-in user, **When** they open their dashboard, **Then**
   the backend returns their journey task progress, their voucher wallet,
   and their saved AI design projects, scoped only to that user.
2. **Given** a signed-in user, **When** they mark a journey task complete,
   **Then** the backend records the update and the dashboard reflects
   "completed" on next load.
3. **Given** a signed-in user, **When** they claim/redeem a voucher,
   **Then** the backend records the claim against that user only.
4. **Given** a request without a valid session, **When** it asks for
   dashboard data, **Then** the backend refuses the request instead of
   returning any user's data.

---

### User Story 3 - Community features (blog and social) run through the backend (Priority: P2)

Visitors read blog posts with author, tag, and comment information; signed-in
users publish posts, like posts, comment, and follow other users. Today these
reads and writes go directly to the database from the browser; going forward,
the backend mediates all of it.

**Why this priority**: High-value engagement feature but lower risk/traffic
than catalog browsing or the personal dashboard, and depends on the same
backend read/write patterns established in P1.

**Independent Test**: Load the blog feed as a visitor, then sign in and
publish a post, like a post, add a comment, and follow another user — each
action must succeed through the backend and be visible on reload.

**Acceptance Scenarios**:

1. **Given** any visitor, **When** they open the blog feed, **Then** the
   backend returns posts with author display info, tags, and comments as
   today.
2. **Given** a signed-in user, **When** they publish a new post, like a post,
   or add a comment, **Then** the backend persists the action attributed to
   that user's identity.
3. **Given** a signed-in user, **When** they follow or unfollow another
   user, **Then** the backend updates the follow relationship and follower
   counts reflect it.
4. **Given** a signed-in user, **When** they attempt to edit or delete
   another user's post or comment, **Then** the backend refuses the action.

---

### User Story 4 - AI consultant and design chat history moves to the backend (Priority: P2)

A user chats with the AI consultant or the customization assistant. Today
each chat's message history is read from and written to the database
directly by the browser; going forward, the backend stores and retrieves
that history, alongside the existing AI reply generation it already
performs.

**Why this priority**: Keeps the AI features consistent with the same
migration and lets chat history sit next to the same AI call the backend
already owns, but it's independent of catalog/dashboard/social and can ship
after them.

**Independent Test**: Open the AI consultant or customization chat, send a
message, reload the page, and confirm prior messages still appear — all
without any direct browser-to-database call.

**Acceptance Scenarios**:

1. **Given** a user with prior chat history, **When** they reopen the AI
   consultant or customization chat, **Then** the backend returns their past
   messages in the original order.
2. **Given** a user sends a new chat message, **When** the exchange
   completes, **Then** the backend stores both the user's message and the
   assistant's reply, attributed to that user.
3. **Given** a chat that references a suggested service, **When** the chat
   view needs that service's details, **Then** the backend supplies them.

---

### User Story 5 - Administrators manage the platform through the backend (Priority: P3)

An administrator uses the admin area to view and moderate profiles, vendors,
services, posts, comments, reviews, journey task definitions, vouchers, and
service requests, and to view aggregate analytics. Today all of this reads
and writes the database directly from the admin browser session; going
forward, the backend performs these operations and independently confirms
the caller is an administrator before doing so.

**Why this priority**: Lower traffic, internal-only surface. It is the most
sensitive (broadest read/write scope) so it depends on every access-control
pattern already proven by the earlier stories, and is naturally sequenced
last.

**Independent Test**: Sign in as an administrator, view each admin panel
(users, vendors, services, blog moderation, journey, vouchers, leads,
analytics), edit and delete a record, and confirm the same actions attempted
by a non-administrator session are refused by the backend.

**Acceptance Scenarios**:

1. **Given** an authenticated administrator, **When** they open any admin
   panel, **Then** the backend returns the full management data for that
   panel.
2. **Given** an authenticated administrator, **When** they edit or delete a
   profile, vendor, service, post, comment, review, journey task, or
   voucher, **Then** the backend applies the change.
3. **Given** an authenticated non-administrator (or unauthenticated caller),
   **When** they call any admin operation directly, **Then** the backend
   refuses it, regardless of what the admin UI would otherwise show.
4. **Given** an administrator views the analytics panel, **When** the panel
   loads, **Then** the backend returns the aggregate website analytics
   figures.

---

### Edge Cases

- What happens when the database is unreachable or slow? The backend must
  fail clearly (a distinguishable error) rather than let the browser hang or
  silently show empty/stale data as if it were current.
- What happens when a user's session expires mid-action (e.g., between
  loading the dashboard and marking a task complete)? The backend must
  reject the write and the frontend must prompt re-authentication rather than
  silently drop the change.
- What happens when two devices for the same user update the same journey
  task or voucher at nearly the same time? The later write wins; no
  duplicate voucher claims or task-completion records are created.
- How does the system handle a request for another user's private data
  (dashboard, chat history, saved designs) by guessing or tampering with an
  identifier? The backend must return the same "not found/forbidden" outcome
  a legitimate absence would produce, without revealing that the record
  belongs to someone else.
- How does the system handle an administrator action attempted through a
  forged or replayed request without a valid session? It must be refused
  the same as any other unauthenticated request.
- What happens to in-flight frontend features during the transition (if
  rolled out incrementally) — is direct database access and backend-routed
  access ever active for the same data at once? This is out of scope for
  this feature: the cut-over is atomic per data domain (a domain is either
  fully backend-routed or not yet migrated), never partially routed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The backend MUST provide a way to read and write every
  application data domain currently accessed directly from the frontend's
  database client: user profiles, vendors, services, service images, blog
  posts, tags, post-tag associations, comments, likes, follows, journey task
  definitions, per-user journey task progress, vouchers, per-user voucher
  claims, saved AI design projects, service requests, AI design generations,
  chat/consultation message history, and website analytics aggregates.
- **FR-002**: The frontend MUST NOT read or write any of the data domains
  listed in FR-001 through a direct database connection after migration;
  all such access MUST go through the backend.
- **FR-003**: The backend MUST continue to allow the frontend to establish
  and maintain a user's sign-in session (login, signup, logout, session
  refresh) exactly as today; this specification does not change how a user
  authenticates, only how their data is subsequently read and written.
- **FR-004**: Every backend operation that reads or writes data scoped to a
  specific user (dashboard progress, vouchers, saved designs, chat history,
  own posts/comments/likes/follows) MUST verify the caller's identity from
  their session and MUST only ever operate on that caller's own data unless
  the caller is a verified administrator.
- **FR-005**: Every backend operation reserved for administrators MUST
  independently verify administrator status on the backend itself; the
  backend MUST NOT rely on the requesting application to have already
  checked this.
- **FR-006**: Publicly readable data (catalog: vendors, services, service
  images; public blog content; aggregate analytics shown to admins) MUST
  remain readable through the backend without requiring a signed-in session,
  matching today's public-read behavior.
- **FR-007**: The backend MUST preserve the existing shape of every response
  the frontend already depends on closely enough that the frontend's
  rendering logic does not need to change beyond swapping its data source
  from a direct database call to a backend call.
- **FR-008**: The backend MUST reject any write to a data domain in FR-001
  that fails basic validity checks (required fields present, correct types,
  referenced records exist) with a response the frontend can present as a
  user-facing error, rather than allowing malformed data into storage.
- **FR-009**: The backend MUST preserve the current data-protection
  guarantees (a user's private data is invisible and unwritable to other
  non-admin users) at least as strictly as today's direct-access protections,
  even though enforcement moves from the database layer to the backend.
  Existing database-level protections MAY remain as a defense-in-depth
  safeguard but MUST NOT be the only enforcement point once the backend
  mediates access.
- **FR-010**: The backend MUST expose the aggregate website-analytics
  figures currently computed for the admin analytics panel, with the same
  metrics and date-range behavior.
- **FR-011**: Removal of direct frontend database access MUST happen data
  domain by data domain, with each domain's frontend code switched to the
  backend at the same time its direct access is removed (no domain is left
  calling the database directly after its migration step, and no domain is
  routed through the backend before its backend endpoint exists and is
  verified).
- **FR-012**: The backend's existing AI consultation and virtual try-on
  behavior (image generation, chat replies) MUST continue to function
  unchanged; this feature only adds/relocates data storage and retrieval
  around those existing capabilities, and does not alter how AI replies are
  produced.

### Key Entities

- **Profile**: A user's identity/profile record (name, contact, role such as
  admin/regular user), linked one-to-one with their authenticated session.
- **Vendor**: A wedding-service provider shown in the catalog, owning one or
  more Services.
- **Service**: An offering from a Vendor, with associated Service Images,
  shown in the catalog and customization flow.
- **Blog Post**: Community content authored by a Profile, with Tags,
  Comments, and Likes.
- **Comment / Like / Follow**: Social interactions tying a Profile to a Post
  or to another Profile.
- **Journey Task (definition)**: A shared, catalog-like list of
  wedding-planning milestones available to all users.
- **User Journey Task (progress)**: One user's completion status against a
  Journey Task definition.
- **Voucher (definition)**: A shared, catalog-like reward/offer available to
  be claimed.
- **User Voucher (claim)**: One user's claim/redemption record against a
  Voucher.
- **AI Design Project**: A user's saved output from the customization/design
  flow (title, category, status, creation time).
- **AI Design Generation**: A record of an individual AI generation attempt
  tied to a design project or service request.
- **Service Request**: A user-submitted request for a vendor/service,
  reviewed by administrators.
- **Chat Message**: A single message in a user's AI consultant or
  customization chat history, attributed to the user or the assistant.
- **Website Analytics (aggregate)**: Rolled-up, non-personal usage figures
  shown only to administrators.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the data domains listed in FR-001 are served through
  the backend, with zero remaining direct-to-database calls in the frontend
  application code.
- **SC-002**: Every page and feature that worked before this change (catalog
  browsing, vendor detail, dashboard, blog, social interactions, AI
  consultant/customization chat, admin panels) continues to work afterward
  with no visible loss of functionality, verified by exercising each user
  story's acceptance scenarios.
- **SC-003**: A non-administrator account can be verified, in 100% of tested
  admin operations, to be refused by the backend even if it directly calls
  the backend operation used by the admin UI.
- **SC-004**: A signed-in user's private data (dashboard, vouchers, saved
  designs, chat history) is verified, across all tested cases, to be
  inaccessible to a different signed-in non-admin user.
- **SC-005**: When the database is unreachable, 100% of affected pages show
  a distinguishable "unavailable" state within the same time budget users
  experience today, instead of hanging indefinitely or showing a blank/broken
  page.

## Assumptions

- Authentication (sign-in, sign-up, sign-out, session refresh) stays as it
  works today: the frontend keeps talking to the identity/session service
  directly, and the backend verifies the resulting session token on each
  request. Only application data access moves behind the backend.
- "The Supabase DB given in the LOMAR frontend" refers to the single
  project/database the frontend is currently configured against; this
  feature does not introduce a second database or change which database is
  authoritative.
- The migration can proceed one data domain at a time (catalog, then
  dashboard, then social/blog, then chat history, then admin) rather than as
  one all-or-nothing cutover, per FR-011.
- File/image storage access (e.g., avatars, vendor images, design
  inputs/outputs) is treated as part of the data domain that owns those
  files and moves to the backend alongside that domain's records; it is not
  called out as a separate story because no dedicated storage-only user
  journey exists today.
- Existing database-level access restrictions may remain in place during
  and after the migration as a secondary safeguard, but are not assumed to
  be removed or relied upon as the primary control once the backend is the
  mediator (see FR-009).
- "Administrator" continues to mean the same role/flag on a user's profile
  that today's admin route guard checks; this feature does not introduce a
  new permission model, only backend-side enforcement of the existing one.
# Schema status

The active persistence contract is defined in `data-model.md`. References in
this historical requirements document to tags, follows, reviews, service
images, or AI-design tables were superseded by the 2026-09-05 schema
simplification.
