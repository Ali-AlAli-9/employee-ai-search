# Implementation Plan: Supabase Auth and User Administration

**Feature**: `005-supabase-auth-admin` | **Date**: 2026-11-15 | **Spec**: [spec.md](./spec.md)

## 1. Architecture

```
Browser ── same-origin ──▶ Next.js proxy ──▶ FastAPI
                                             │
                     ┌───────────────────────┼────────────────────────┐
                     ▼                       ▼                        ▼
            identity/local.py        identity/supabase.py     db.py (SQLite/PG)
            scrypt + sessions        GoTrue REST + JWT         documents, chunks,
            (dev/tests/offline)      + profiles read model     queries, traces,
                                                               profiles
                                             │
                                             ▼
                                    Supabase Auth (GoTrue)
                                    Supabase Postgres (pooler)
```

Two identity providers behind one facade:

* `local` — the spec-004 implementation, unchanged. Default when
  `SUPABASE_URL` is empty. Keeps the offline demo and the whole test suite
  independent of the cloud.
* `supabase` — GoTrue owns identities; the platform owns a `profiles` read model.

Everything above the facade (`require_role`, `/auth/*` responses, the UI) is
provider-agnostic.

## 2. Token and cookie model (Supabase mode)

| Cookie | Flags | Contents |
| --- | --- | --- |
| `eais_access` | HttpOnly, SameSite=Lax, Secure in production | Supabase access JWT (1 h) |
| `eais_refresh` | HttpOnly, SameSite=Lax, Secure in production | rotating refresh token |
| `eais_csrf` | readable, same flags minus HttpOnly | random 24-byte token |

* **Verification**: local, with `PyJWT`. HS256 uses `SUPABASE_JWT_SECRET`;
  asymmetric keys use the project JWKS (`.../auth/v1/.well-known/jwks.json`),
  cached by `PyJWKClient`. Required claims: `exp`, `sub`; `aud=authenticated`;
  `iss={SUPABASE_URL}/auth/v1` when the URL is known.
* **Refresh**: the auth dependency sees an expired access cookie plus a refresh
  cookie, calls `POST /token?grant_type=refresh_token`, writes the rotated pair
  onto the outgoing response, and continues. Rotation is invisible to the
  browser and to SSE streams.
* **CSRF**: double submit without server state — the header must equal the
  readable cookie, and both must exist. The token is issued at login/register/
  demo and deliberately *not* rotated on refresh (the client caches it).
* **Logout**: refresh once if needed, then `POST /logout` with the access token
  and `scope=local`, then clear all three cookies. Idempotent.

## 3. Profiles read model

GoTrue's admin list supports only `page`/`perPage` — no search, no filtering.
Listing therefore reads a local projection that is upserted whenever the
platform learns about a user:

```sql
CREATE TABLE profiles (
  id TEXT PRIMARY KEY,          -- Supabase auth.users.id
  email TEXT,
  role TEXT NOT NULL DEFAULT 'viewer',
  display_name TEXT,
  is_guest INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_sign_in_at TEXT
);
```

* Written on login, register, demo, admin create, admin update and admin sync.
* Missing row (user created in the Supabase dashboard) → upserted from the JWT
  claims on first authenticated request.
* **Authorisation reads the profile**, so a demotion or deactivation is
  effective on the next request instead of after the JWT expires.
* Search uses `ILIKE` on Postgres and `LIKE` on SQLite (ASCII case-insensitive);
  the helper branches on `db.dialect()`.
* Supabase stays the source of truth; `POST /auth/users/sync` repairs drift by
  pulling up to `SYNC_MAX_PAGES × 1000` users.

## 4. Admin API

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/auth/users` | `page`, `page_size`, `q`, `include_guests`; reads `profiles` |
| `POST` | `/auth/users` | create with an explicit role (existing route, now also Supabase) |
| `PATCH` | `/auth/users/{id}` | `{role?, is_active?}` |
| `POST` | `/auth/users/{id}/password-reset` | `202`; `501` in local mode |
| `DELETE` | `/auth/users/{id}` | guests only |
| `POST` | `/auth/users/sync` | pull GoTrue → profiles |

Guards in one place (`_guard_target`): not yourself, never the last active admin,
never an API-key principal, and delete is guest-only. Violations are `409` with a
readable detail.

The recovery link is completed by the public `POST /auth/password-reset`
(`{access_token, password}` → GoTrue `PUT /user` → `204`, `501` in local mode).
The frontend page is `app/auth/reset/page.tsx`; `PASSWORD_RESET_REDIRECT_TO`
points the email at it.

## 5. Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTH_PROVIDER` | auto | `supabase` when `SUPABASE_URL` is set, else `local` |
| `SUPABASE_URL` | empty | project URL, e.g. `https://abcd.supabase.co` |
| `SUPABASE_ANON_KEY` | empty | publishable/anon key for password, refresh, anonymous and recover calls |
| `SUPABASE_SERVICE_ROLE_KEY` | empty | **server only**; admin API and bootstrap |
| `SUPABASE_JWT_SECRET` | empty | HS256 verification (legacy projects) |
| `SUPABASE_JWKS_URL` | derived | override the discovery endpoint |
| `SUPABASE_TIMEOUT_SECONDS` | `15` | HTTP timeout for GoTrue calls |
| `DATABASE_URL` | empty | `postgresql://...` Supabase pooler for durable data |
| `PASSWORD_RESET_REDIRECT_TO` | empty | recovery-email destination (`https://<web>/auth/reset`); Site URL is the fallback |

Supabase deployment notes: use the **transaction pooler** URL (port 6543); the
data layer sets `prepare_threshold=0` for pooler hosts. The direct URL (5432) is
the fallback if the pooler is unavailable.

## 6. Failure behaviour

| Situation | Result |
| --- | --- |
| Supabase configured but service key missing | login works; admin routes `503`; health says `admin_api:false` |
| Access token expired, refresh valid | transparent rotation, request proceeds |
| Refresh rejected (revoked/banned) | cookies cleared, `401` |
| JWT signed with an unknown key | `401`, never a fallback |
| GoTrue unreachable | `502`/`503` with a readable detail; local data untouched |
| Anonymous sign-ins disabled in the project | `/auth/demo` → `403`; UI hides the guest button via health |
| Account disabled in `profiles` | `401` on the next request |
| Last active admin demotion | `409` with an explicit message |
| Password reset for an unknown address | `202` (no enumeration) |
| Local mode password reset | `501` (no email transport) |

## 7. Testing strategy

* **Unit / API (no network)**: a stub GoTrue built on `httpx.MockTransport`
  exercises login, refresh rotation, JWT verification (HS256), anonymous users,
  admin list/update/ban/recover/delete, and asserts the service key never leaks.
* **Local provider**: the full spec-004 suite keeps running; new admin tests
  cover search, pagination, guest visibility, guards and deactivation.
* **Postgres**: opt-in with `TEST_DATABASE_URL`; now also round-trips a profile.
* **Frontend**: `tsc --noEmit`, `next build`, and a live smoke through the real
  Next.js proxy (cookies + CSRF).

## 8. Delivery order

1. Config, identity package, JWT verification, GoTrue client.
2. `profiles` schema and queries; security dependency for both providers.
3. Auth routes and admin routes; bootstrap.
4. Admin panel + copy + API client.
5. Tests, docs, Render blueprint, smoke test.
