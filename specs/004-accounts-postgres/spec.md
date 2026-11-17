# Feature Specification: Accounts, Sessions and Durable Storage

**Feature Branch**: `004-accounts-postgres`

**Created**: 2026-11-15

**Status**: Implemented

**Input**: User description: "Add real login and user management, backed by a
free Postgres database so accounts survive a Render deploy."

## Why

The platform authenticates with three static API keys. That is fine for scripts
and CI, but it means every browser visitor shares the same identity: chat
history is scoped to a role, not a person, and the Next.js proxy injects the
admin key so *any* visitor can upload or delete documents.

Two problems follow:

1. **No real identity.** Per-user history, per-user quotas and any future
   sharing model are impossible.
2. **Accounts must not live on the free instance's `/tmp` disk.** Render wipes
   it on every deploy, so a login system backed only by SQLite would lose every
   account on every release — worse than having no login at all.

This feature adds invitation-only accounts and server-side sessions on top of
the existing API keys, and makes the database layer portable to Postgres via
`DATABASE_URL`. SQLite remains the zero-setup default for local work and tests.

## User Scenarios & Testing

### Primary user story

As a visitor, I open the app and start chatting immediately as a **guest**. I
can create an account with an invite code (or sign in) to keep my chat history
across visits. As the operator, I get an admin account from environment
variables; every signed-in account (guests included) can upload, while deleting
stays admin-only.

### Acceptance scenarios

1. **Given** no cookie, **When** I open the app, **Then** the frontend creates a
   guest session and my chat works without any sign-up.
2. **Given** a valid invite code, **When** I register with an email and a
   password, **Then** a user is created, a session cookie is set, and my chat
   history is scoped to my user id.
3. **Given** the same email, **When** someone registers again, **Then** the API
   answers `409` without revealing anything about the existing password.
4. **Given** a wrong password, **When** I sign in, **Then** the API answers
   `401` with one generic message, and repeated attempts are rate-limited.
5. **Given** a guest session, **When** I upload a document, **Then** the API
   accepts it; **When** I try to delete it, **Then** the API answers `403` and
   the delete control is hidden in the UI.
6. **Given** an authenticated session, **When** I POST without the CSRF header,
   **Then** the API answers `403`; the same request with the header succeeds.
7. **Given** the operator sets `ADMIN_EMAIL` and `ADMIN_PASSWORD`, **When** the
   API starts, **Then** that account exists with the `admin` role and can sign
   in. The password is never logged.
8. **Given** `DATABASE_URL` points at Postgres, **When** the API starts, **Then**
   the schema is created there and accounts survive a redeploy.
9. **Given** an existing API key, **When** a script calls `/search`, **Then**
   behaviour is unchanged (no cookie, no CSRF header required).
10. **Given** a session token, **When** it is stored, **Then** the database holds
    only its SHA-256 hash, never the token itself.

### Edge cases

- Expired session → `401`, cookie cleared by the client on the next sign-in.
- Deactivated user (`is_active = 0`) → `401` even with a valid cookie.
- Logout with no session → `204` (idempotent).
- Demo login disabled (`DEMO_LOGIN_ENABLED=false`) → `403` and the UI offers the
  sign-in form instead of a guest session.
- Registration with `INVITE_CODE` unset → `403` (no public sign-up).
- Password shorter than `PASSWORD_MIN_LENGTH` → `400`, never stored.
- Postgres unreachable at boot → readiness reports `503`; the app does not
  silently fall back to SQLite (that would split identities).
- `DATABASE_URL` set but the psycopg driver missing → explicit startup error
  naming the missing extra.

## Requirements

### Functional

- **FR-001**: Add `users` and `sessions` tables to the same database layer used
  by documents, queries and traces.
- **FR-002**: `DATABASE_URL` (Postgres) MUST select Postgres; empty MUST keep
  SQLite at `DATA_DIR/app.db`.
- **FR-003**: Passwords MUST be hashed with stdlib `hashlib.scrypt` using a
  per-user random salt; plaintext MUST never be stored or logged.
- **FR-004**: Sessions MUST be server-side rows keyed by SHA-256 of a random
  token; the cookie MUST be `HttpOnly`, `SameSite=Lax`, `Secure` in production.
- **FR-005**: Every state-changing request authenticated by cookie MUST require
  an `X-CSRF-Token` header matching the session's CSRF hash.
- **FR-006**: API keys MUST keep working for automation and MUST NOT require a
  CSRF header.
- **FR-007**: `POST /api/v1/auth/demo` MUST create a guest session (viewer role)
  unless disabled.
- **FR-008**: `POST /api/v1/auth/register` MUST require an invite code and assign
  the `user` role; it MUST never create an admin.
- **FR-009**: `POST /api/v1/auth/login`, `/logout` and `GET /auth/me` MUST exist;
  login errors are generic.
- **FR-010**: Admin bootstrap from `ADMIN_EMAIL` / `ADMIN_PASSWORD` MUST run at
  startup and be idempotent.
- **FR-011**: `uploaded_by`, `queries.user_id` and chat history MUST use the
  principal's stable id, not the role name.
- **FR-012**: The Next.js proxy MUST forward cookies both ways, MUST stop
  injecting the admin API key, and MUST forward a caller-supplied CSRF header for
  unsafe methods (deriving it from the readable cookie would defeat the double
  submit); the API client MUST send that header from `eais_csrf`.
- **FR-013**: The backend MUST keep the SQLite path working with no new required
  dependency; Postgres support is imported lazily.
- **FR-014**: Auth routes MUST use their own per-IP rate-limit bucket.

### Non-functional

- Scrypt parameters: `n=2**14, r=8, p=1`, so a 0.1 CPU instance can still verify
  in well under a second.
- Session lifetime defaults to 7 days (`SESSION_TTL_HOURS`).
- No email is ever sent; invitation is a shared code.
- No secret (password, session token, CSRF token) is written to logs or traces.

## Success Criteria

- **SC-001**: `pytest` proves register/login/logout/me, role enforcement, CSRF,
  expiry, deactivation, API-key compatibility and token hashing.
- **SC-002**: A test proves the raw session token is absent from the database.
- **SC-003**: A test proves a guest can upload but cannot delete, and an admin can do both.
- **SC-004**: The existing 71 tests stay green (API keys unchanged).
- **SC-005**: `tsc --noEmit` and `next build` pass.
- **SC-006**: With `DATABASE_URL` unset, a fresh clone still runs with SQLite and
  no psycopg installed.
- **SC-007**: An optional Postgres integration test runs when
  `TEST_DATABASE_URL` is set and is skipped otherwise.

## Assumptions

- The operator provides a free durable Postgres (Neon, Supabase or Render
  Postgres) for production; the repo cannot provision it.
- The browser reaches the API through the same-origin Next.js proxy, so cookies
  are first-party. Direct browser → API mode remains a local debugging option.
- One process serves the app; in-memory rate limiting stays per instance.

## Out of scope

- Password reset by email, email verification, OAuth/SSO.
- Per-document ACLs or sharing between users.
- Session listing/revocation UI beyond "sign out this device".
- Migrating existing Render `/tmp` data (it is ephemeral by definition).
