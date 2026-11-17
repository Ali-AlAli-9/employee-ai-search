# Feature Specification: Supabase Auth and User Administration

**Feature**: `005-supabase-auth-admin` | **Status**: Implemented | **Date**: 2026-11-15

## Summary

Move identity to **Supabase Auth** (GoTrue) and add a first-class **user
administration panel**. The browser keeps talking to the same FastAPI surface
(`/api/v1/auth/*`) through the Next.js proxy, so the product experience does not
change: password sign-in, public registration (invite-code optional), guest sessions, and the same
CSRF rules. Supabase becomes the system of record for identities and passwords;
the platform keeps a small read model of profiles for search, pagination and
instant role/deactivation checks.

The relational data (documents, chunks, queries, traces, profiles) moves to
Supabase Postgres through `DATABASE_URL`, which makes the whole deployment
durable across Render redeploys.

## Why

Spec 004 stored accounts in SQLite (`/tmp`) or a time-limited Render Postgres and
shipped no management UI. Real deployments need:

1. identities that survive redeploys and are not maintained by hand;
2. an operator who can list, search, promote, demote, disable and reset people
   without touching SQL;
3. one place that owns password hashing, token rotation and revocation
   (Supabase Auth), instead of bespoke session code that must be audited forever.

## User stories

### US-1 — Sign in through Supabase (P1)

As a visitor, I can create an account (open by default, or with an invite code when the deployment
sets one), sign in, sign out and use a guest session, and the platform behaves exactly as before.

**Acceptance**

- `POST /auth/login` verifies the password with Supabase and sets HttpOnly
  session cookies; wrong credentials return the same generic `401` as before.
- `POST /auth/register` is public when `INVITE_CODE` is unset, and requires the
  shared code when the deployment sets one. The account is created already
  confirmed and signed in. `GET /health` reports `registration: true` plus
  `invite_required` so the UI asks for the code only when it is needed.
- `POST /auth/demo` creates a Supabase **anonymous** user with role `viewer`
  when anonymous sign-ins are enabled; otherwise `403` with a clear message.
- `GET /auth/me` returns the current profile; expired access tokens are
  refreshed transparently, rotating the refresh token.
- `POST /auth/logout` revokes the Supabase session and clears the cookies.
- API keys (`X-API-Key`) keep working for scripts and bypass CSRF.

### US-2 — Administer users (P1)

As an admin, I open **Manage users** from the account panel and can:

- search by email or display name, with pagination;
- see role, status (active/disabled), guest marker and last sign-in;
- change a role between `viewer`, `user` and `admin`;
- disable or re-enable an account;
- send a password-reset email;
- reveal guest accounts (hidden by default) and delete them;
- refresh the list from Supabase when accounts were created elsewhere.

**Acceptance**

- Every route is admin-only, CSRF-protected for cookie sessions, and rate
  limited; the panel is not rendered for other roles.
- Self-demotion and self-deactivation are refused, and so is removing the last
  active admin.
- Disabling an account takes effect on its next request (profiles is checked on
  every authentication), not after the JWT expires.
- A reset never reveals whether the address exists.
- The emailed link opens `/auth/reset`, where the new password is submitted with
  the link's access token once (`POST /auth/password-reset`, `204`); the old
  password stops working and neither the token nor the password is stored or
  logged.
- Guests are excluded unless `include_guests=true`; only guests can be deleted
  from this surface.
- The service-role key never leaves the backend: it is not in any response,
  bundle, log or trace.

### US-3 — Deploy with Supabase (P1)

As an operator, I set `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL` (Supabase pooler) and the existing
admin/invite variables, redeploy, and everything survives.

**Acceptance**

- `ADMIN_EMAIL` / `ADMIN_PASSWORD` create or repair the operator in Supabase at
  every start (password updated, role set to admin, ban cleared).
- Health reports the auth provider, whether guests and registration are open,
  whether an invite code is required (`invite_required`), and whether the admin
  API is configured — no secrets.
- With no Supabase variables the app still runs locally on SQLite with the
  spec-004 account implementation (`AUTH_PROVIDER=local`), so tests and the
  offline demo need no cloud account.
- Missing/invalid Supabase configuration fails loudly in health and logs, never
  silently downgrades to local auth.

## Functional requirements

- **FR-001**: `AUTH_PROVIDER` selects `local` or `supabase`; it defaults to
  `supabase` when `SUPABASE_URL` is set, else `local`.
- **FR-002**: In Supabase mode, credentials are verified by GoTrue
  (`POST /auth/v1/token?grant_type=password`); the platform never stores a
  password or a password hash.
- **FR-003**: Access and refresh tokens live in HttpOnly, SameSite=Lax, Secure-in
  production cookies (`eais_access`, `eais_refresh`). The CSRF cookie
  (`eais_csrf`) stays readable for the double-submit header.
- **FR-004**: Access tokens are verified locally, never trusted unverified. The
  verification key follows the token header: `HS256` uses `SUPABASE_JWT_SECRET`
  (legacy projects), while `ES256`/`RS256` use the project JWKS derived from
  `SUPABASE_URL`. `sub`, `exp`, `aud` and (when configured) `iss` are checked.
  A missing/unreachable key is a deployment error (`reason=no_verifier`), not a
  rejected session, so the cookies survive a configuration fix.
- **FR-005**: On an expired access token, the backend refreshes with the stored
  refresh token, rotates both cookies and continues the request; a failed
  refresh clears the cookies and returns `401`.
- **FR-006**: Role is read from `app_metadata.role`, never `user_metadata`
  (user-writable). Unknown or missing roles map to `viewer`.
- **FR-007**: Anonymous users (`is_anonymous`) are guests with role `viewer`;
  they may upload documents but cannot delete them.
- **FR-008**: `profiles` mirrors Supabase users for listing/searching and for
  instant `is_active`/role checks. It is repaired on login, registration,
  creation, update and an explicit admin sync.
- **FR-009**: Admin routes: list, create, update (role/status), password reset,
  delete guest, sync. All require `admin`, all enforce the guards above.
- **FR-010**: `ADMIN_EMAIL`/`ADMIN_PASSWORD` bootstrap is idempotent in both
  modes and never logs the password.
- **FR-011**: The Next.js proxy stays credential-neutral: it forwards cookies,
  a caller-supplied CSRF header and an optional API key; it holds no Supabase
  key and never derives CSRF.
- **FR-012**: The admin panel is bilingual (English/Arabic) and matches the
  existing visual language.

## Non-functional

- **NFR-001**: No password, token, service key or Supabase secret is logged or
  returned by any endpoint.
- **NFR-002**: The service-role key is read from the environment only and used
  exclusively in server-side admin calls.
- **NFR-003**: A Supabase outage must not corrupt local data; auth endpoints
  return `502`/`503` with a readable detail.
- **NFR-004**: `DATABASE_URL` pointing at the Supabase transaction pooler must
  work (no server-side prepared statements).
- **NFR-005**: The backend test suite runs with no network access (stubbed
  GoTrue); a real Supabase round trip is opt-in via environment variables.

## Out of scope

- Email verification flows, MFA, SSO, per-document ACLs.
- Supabase Storage for document originals.
- Renaming users, editing emails, or transferring ownership.
- Audit log of administrative actions (listed as a follow-up; the app log does
  record the actor and the target at INFO).

## Success criteria

- **SC-001**: `pytest` proves login, refresh rotation, logout, guest sessions,
  JWT verification, CSRF, the admin routes, every guard and the Supabase client
  contract; the suite needs no network.
- **SC-002**: `tsc --noEmit` and `next build` pass; the admin panel is usable in
  both languages at phone width.
- **SC-003**: On Render, a redeploy keeps accounts and documents; signing in with
  the bootstrap admin works after the first deploy.
- **SC-004**: API-key scripts and existing history partitions are unchanged.
