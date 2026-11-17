---
description: "Task list for accounts, sessions and durable storage (spec 004)"
---

# Tasks: Accounts, Sessions and Durable Storage

**Input**: [`spec.md`](./spec.md) · [`plan.md`](./plan.md) · [`data-model.md`](./data-model.md)

## Phase 1: Contracts and configuration

- [X] T001 Write `spec.md`, `plan.md`, `data-model.md`, `tasks.md` and the OpenAPI delta
- [X] T002 Add `SESSION_TTL_HOURS`, `SESSION_SECURE`, `INVITE_CODE`,
      `DEMO_LOGIN_ENABLED`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`,
      `PASSWORD_MIN_LENGTH`, `COOKIE_DOMAIN` and
      `RATE_LIMIT_AUTH_PER_MINUTE` to `config.py` and `.env.example`
- [X] T003 Register an `auth` scope in `ratelimit.py`

## Phase 2: Database portability (tests first)

- [X] T004 Write failing tests proving SQLite stays the default and that
      `?` placeholders, upserts and schema creation stay portable
- [X] T005 Rewrite `db.py` around a small connection wrapper: SQLite and a lazy
      `psycopg` pool selected by `DATABASE_URL`, `?` → `%s` translation,
      `information_schema` introspection, portable `ON CONFLICT` upserts
- [X] T006 Add `users` and `sessions` tables plus `create_user`,
      `get_user_by_email`, `get_user`, `update_user`, `create_session`,
      `get_session`, `delete_session`, `delete_expired_sessions`
- [X] T007 Export `db.IntegrityErrors` so uploads catch SQLite *and* Postgres
      duplicates without importing either driver into `api.py`

## Phase 3: Authentication (tests first)

- [X] T008 Write failing tests in `backend/tests/test_auth.py` covering demo,
      register, login, logout, me, CSRF, role enforcement, expiry,
      deactivation, token hashing, API-key compatibility and admin bootstrap
- [X] T009 Add `backend/app/auth.py`: scrypt hashing/verification, token
      generation and hashing, cookie helpers, email/password validation,
      `bootstrap_admin()`
- [X] T010 Replace role strings with a `Principal` value object in
      `security.py`; resolve API key or session cookie; enforce CSRF for
      cookie-authenticated unsafe methods; keep API keys exempt
- [X] T011 Add `backend/app/auth_api.py` with `POST /auth/demo`,
      `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`,
      `GET /auth/me` and `POST /auth/users`
- [X] T012 Update `api.py` routes to take `Principal` and persist
      `principal.id`; catch `db.IntegrityErrors` on duplicate uploads
- [X] T013 Wire the auth router, CORS credentials policy and admin bootstrap
      into `main.py`; report auth flags from `/health`
- [X] T014 Add the Postgres integration test gated on `TEST_DATABASE_URL`

## Phase 4: Frontend

- [X] T015 Add `lib/auth.ts` (me/demo/login/register/logout + CSRF memory)
- [X] T016 Add `credentials` and the CSRF header to every API call, including
      the XHR upload path
- [X] T017 Add `components/AuthPanel.tsx` (sign in, create account, guest,
      sign out) with Arabic and English copy
- [X] T018 Bootstrap guest/demo sessions in `ChatInterface`, add the account
      chip and pass `canManage` to `DocumentPanel`
- [X] T019 Hide delete for non-admins in `DocumentPanel`; upload is offered to any signed-in account
- [X] T020 Forward cookies both ways and a caller-supplied `X-CSRF-Token` in the
      Next.js proxy (never derive it from the cookie); stop injecting
      `BACKEND_API_KEY`

## Phase 5: Verification and docs

- [X] T021 Run the full backend suite, `tsc --noEmit` and `next build`
- [X] T022 Update `README.md`, `ARCHITECTURE.md`, the 001 quickstart,
      `.env.example`, `render.yaml` and `docker-compose.yml`
- [X] T023 Commit, push to `origin main`, and note that a Render redeploy is
      required for the new endpoints and environment variables
