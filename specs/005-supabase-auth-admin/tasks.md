# Tasks: Supabase Auth and User Administration

**Feature**: `005-supabase-auth-admin` | **Input**: [spec.md](./spec.md), [plan.md](./plan.md)

**Rule**: tests for a behaviour are written before the code that satisfies it.
Local mode keeps the spec-004 suite green at every step.

## Phase 1: Foundations

- [X] T001 Add `httpx` and `PyJWT[crypto]` to `backend/requirements.txt`
- [X] T002 Add Supabase and provider settings to `config.py`
      (`AUTH_PROVIDER` auto-detect, URL, anon, service role, JWT secret, JWKS
      URL, timeout) with safe properties and no secret defaults
- [X] T003 Add the `profiles` table, indexes and portable upsert/select helpers
      to `db.py` (search, paginate, count, delete, last-admin count)
- [X] T004 Make the Postgres pool transaction-pooler safe: `prepare_threshold=0`
      for pooler hosts, pass through `sslmode`, keep `min_size=0`

## Phase 2: Supabase identity (tests first)

- [X] T005 Write `tests/test_identity_supabase.py` with a stubbed GoTrue
      (`httpx.MockTransport`): password grant, refresh rotation, anonymous
      signup, admin create/update/ban/recover/delete, error mapping and a
      "service key never leaks" assertion
- [X] T006 Write JWT tests: valid HS256, wrong signature, expired, wrong
      audience, missing `sub`, `is_anonymous`, unknown `app_metadata.role`
- [X] T007 Implement `backend/app/identity/supabase.py`: GoTrue HTTP client
      (public + admin headers), token/user mapping to `IdentityUser`
- [X] T008 Implement local JWT verification (`HS256` secret or cached JWKS) with
      required claims and issuer check
- [X] T009 Implement the identity facade `backend/app/identity/__init__.py`
      (`provider()`, `login`, `register`, `demo`, `refresh`, `logout`,
      `verify`, `admin_*`, `bootstrap_admin`) dispatching to local or Supabase

## Phase 3: Authentication surface

- [X] T010 Rewrite `security.resolve_principal` to use the facade, read
      `profiles` for role/status, refresh expired access tokens and attach
      rotated cookies to the response
- [X] T011 Keep CSRF semantics: hashed compare in local mode, double-submit in
      Supabase mode; API keys exempt in both
- [X] T012 Update `auth_api.py` for the provider-neutral `{user, csrf_token}`
      contract, transparent refresh, and a Supabase-aware `/me`
- [X] T013 Supabase admin bootstrap (create/repair/unban, role=admin, no
      password in logs); keep the local implementation untouched

## Phase 4: Administration API (tests first)

- [X] T014 Write `tests/test_admin_users.py` on the local provider: list,
      search, pagination, guest hiding, role change, disable, reset `501`,
      last-admin and self guards, non-admin `403`, CSRF `403`, API key bypass
- [X] T015 Implement `GET/POST /auth/users`, `PATCH /auth/users/{id}`,
      `POST /auth/users/{id}/password-reset`, `DELETE /auth/users/{id}`,
      `POST /auth/users/sync` with one shared guard helper
- [X] T016 Upsert profiles on every identity event; add the admin sync
      (paged `listUsers`, capped by `SYNC_MAX_PAGES`)
- [X] T017 Extend `/health` with `auth.provider`, `demo`, `registration`,
      `invite_required`, `password_reset` and `admin_api` (no secrets); update readiness

## Phase 5: Frontend

- [X] T018 Add admin calls to `frontend/lib/auth.ts` and
      `AdminUser`/`UserPage` types
- [X] T019 Add English and Arabic copy for the panel: title, search,
      guests toggle, role labels, enable/disable, reset, delete, sync,
      pagination, guard errors
- [X] T020 Build `components/AdminUsersPanel.tsx`: search, table, role select,
      status toggle, reset, delete guest, guests switch, pagination, sync;
      mobile-friendly and keyboard accessible
- [X] T021 Open the panel from `AuthPanel` for admins only and mount it in
      `ChatInterface`; refresh the document panel's `canManage` after a role
      change
- [X] T021b Add `app/auth/reset/page.tsx` and `completePasswordReset` so the
      emailed recovery link actually sets a new password (bilingual copy, token
      read from the fragment and never stored)

## Phase 6: Verification and delivery

- [X] T022 Run the backend suite (local provider) and the new Supabase tests;
      `tsc --noEmit`; `next build`
- [X] T023 Live smoke through the Next.js proxy: guest, admin login, user list,
      role change, disable/enable, reset, guest cleanup, CSRF enforcement
- [X] T024 Update `README.md`, `ARCHITECTURE.md`, the 001 quickstart,
      `.env.example`, `render.yaml` (Supabase variables, no Render database)
      and `docker-compose.yml`
- [X] T025 Document the Supabase setup checklist: project, anonymous sign-ins,
      redirect URLs for reset, pooler URL, service key handling
- [X] T026 Commit and push to `origin main`; list the Render variables the user
      must set and the redeploy step
- [X] T027 Make registration public by default: `INVITE_CODE` unset allows open
      sign-up, setting it switches to invite-only; `/health` adds
      `invite_required` and the form hides the code unless required (tests cover
      both modes)
