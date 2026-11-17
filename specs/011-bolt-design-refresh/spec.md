# Feature Specification: Bolt Design Refresh

**Feature Branch**: `011-bolt-design-refresh`

**Created**: 2026-11-20

**Status**: Draft

**Input**: User instruction (`استخدم هذا المشروع لتعديل مشروعنا الاصلي`) pointing to the
local Bolt prototype at `D:\project-bolt-sb1-n9fg77cm\project`. The prototype is used
**as a visual reference only**; none of its mock data, mock auth or mock chat logic
is imported.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Familiar, polished workspace (Priority: P1)

A signed-in employee lands in a workspace with a persistent sidebar (Chat, Library,
Users for admins, Settings) and a top bar with language, theme, key status and
account controls. The visual language comes from the Bolt prototype: blue primary,
emerald accent, neutral surfaces, rounded cards, Inter/Noto Naskh Arabic typography,
subtle entrance animations and a responsive mobile drawer.

**Why this priority**: the repo is a portfolio demo; the UI must look production-ready
without changing the backend contract or the interaction model.

**Independent Test**: render the shell with an admin user and assert the four nav
items appear; render with a guest and assert Users is absent; toggle language and
assert `dir="rtl"` and Arabic labels; toggle theme and assert the theme attribute.

**Acceptance Scenarios**:

1. **Given** an authenticated admin, **When** the workspace loads, **Then** Chat,
   Library, Users and Settings are all navigable from the sidebar.
2. **Given** a guest or demo user, **When** the workspace loads, **Then** the Users
   nav item is hidden and direct use of admin actions stays server-blocked.
3. **Given** the viewport is narrow, **When** the menu button is pressed, **Then** a
   drawer with the same nav items opens and closes on overlay click.
4. **Given** either language, **When** the user toggles it, **Then** all shell and
   view labels change and the document direction follows (`rtl` for Arabic).

---

### User Story 2 - Full-page library, admin and settings views (Priority: P1)

The old compact document/key/admin panels become full views that reuse the existing
real API functions. The library shows real uploaded sample documents with stats,
drag-and-drop upload, search and admin-only delete/replace confirmation. The admin
view keeps search, pagination, role/status changes, guest cleanup, password reset
and sync. Settings keeps appearance controls and the request-scoped BYOK form.

**Why this priority**: it delivers the prototype's information density while keeping
the established permissions and privacy boundary.

**Independent Test**: unit-test the pure formatting helpers (`formatBytes`, `timeAgo`)
and run the existing 34 frontend tests plus type-check and lint.

**Acceptance Scenarios**:

1. **Given** signed-in guests, **When** they open the library, **Then** they can upload
   but cannot delete another user's document; the delete control is hidden.
2. **Given** an admin, **When** a duplicate upload is detected, **Then** the existing
   409 replace confirmation is offered before anything is deleted.
3. **Given** a non-admin, **When** they open the admin view directly, **Then** no
   user data is rendered and the server still rejects admin API calls.
4. **Given** BYOK is disabled by health, **When** settings opens, **Then** the key form
   is hidden and no key is sent.
5. **Given** a key is saved, **When** it is displayed in settings, **Then** it is
   masked and still lives only in `sessionStorage`, never in logs or localStorage.

---

### User Story 3 - Chat and account surfaces follow the same system (Priority: P2)

Chat messages, citations, empty state and composer adopt the new tokens and spacing
without changing SSE streaming. If no identity is available, a split-screen account
view replaces the old compact panel and uses the same real login/register/logout
functions, including the demo-guest path.

**Why this priority**: a consistent look across every surface is required for the
launch video and screenshot assets.

**Independent Test**: run `npm.cmd test -- EmptyState.test.tsx` and `npm.cmd test`;
verify the existing `SAMPLES`/localized copy still behave.

**Acceptance Scenarios**:

1. **Given** a streamed answer with citations, **When** it renders, **Then** every
   citation shows only the server-provided page label and the source filename.
2. **Given** no messages, **When** the chat view opens, **Then** localized sample
   questions are clickable and send through the existing `send()` path.
3. **Given** no session, **When** the account view opens, **Then** sign-in,
   registration (when enabled) and demo-guest login use the existing API.

---

### User Story 4 - Constraints and history stay intact (Priority: P3)

No backend, environment or deployment change is made. The repository keeps exactly
one commit: changes are folded into the existing root commit by amend; the operator
performs the force-push manually. README and ARCHITECTURE describe the refreshed UI
without changing the free/offline default, the `402` contract, the exact
`LLM_KEY_REQUIRED_DETAIL` literal or the sample-data-only demo.

**Why this priority**: protects the prior acceptance gates and deployment contract.

**Independent Test**: `git rev-list --count HEAD` stays `1`; backend tests stay
`216 passed, 1 skipped`; no `.env`, key or secret appears in any source file.

**Acceptance Scenarios**:

1. **Given** the refreshed tree, **When** all gates run, **Then** backend tests,
   frontend tests, type-check, lint and build pass.
2. **Given** the amended commit, **When** git history is inspected, **Then** there is
   still one commit on `main` and `origin/main` is unchanged until the operator pushes.
3. **Given** any UI screenshot, **When** it is reviewed, **Then** it contains only
   local `sample-data`, never the Bolt prototype's mock users/documents.

## Scope boundaries

- The Bolt folder is read-only reference; no file from it is copied verbatim.
- No new runtime dependency, service, provider, hosted quota or model download.
- No backend route, config default, auth rule or storage change.
- The explainer video is not re-recorded in this spec; a later decision may refresh
  it so the captured UI matches the new design.
