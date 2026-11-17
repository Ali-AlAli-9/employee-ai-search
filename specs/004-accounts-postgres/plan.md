# Implementation Plan: Accounts, Sessions and Durable Storage

**Spec**: [`spec.md`](./spec.md) · **Branch**: `004-accounts-postgres` · **Date**: 2026-11-15

## Technical approach

Add identity *beside* the existing API keys, not instead of them. A single
dependency resolves either credential into one value object:

```
X-API-Key ─────────────────────────────┐
                                        ├─▶ Principal(kind, id, role, email)
Cookie: eais_session ─▶ sha256 ─▶ sessions JOIN users ─┘
                                        │
                     unsafe method? ─▶ X-CSRF-Token must match sessions.csrf_hash
```

Every route keeps `Depends(require_role(...))`; only its return type changes from
`str` to `Principal`. `_persist` and chat history use `principal.id`, which is the
user UUID for sessions and the role name for API keys (so existing scripts keep
their old history partition).

### Database portability

`db.py` keeps its public surface (`get_conn`, `create_document`, ...). Internally:

| Concern | SQLite | Postgres |
| --- | --- | --- |
| Driver | stdlib `sqlite3` | `psycopg` 3 + `psycopg_pool`, imported lazily |
| Placeholders | `?` | translated to `%s` by a thin wrapper |
| Rows | `sqlite3.Row` | `dict_row` |
| Schema | statement list | same statement list |
| PRAGMAs | WAL + foreign keys | skipped |
| Column introspection | `PRAGMA table_info` | `information_schema.columns` |
| Upsert | `ON CONFLICT ... DO UPDATE` | same (portable SQL) |

`DATABASE_URL` is normalised (`postgres://` → `postgresql://`). The pool is
created on first use, `min_size=0`, `max_size=4`, so a sleeping free instance
does not hold connections open.

### Accounts and sessions

```sql
users(id, email UNIQUE, password_hash, role, display_name, is_active,
      is_guest, created_at, last_login_at)
sessions(id, user_id→users, token_hash UNIQUE, csrf_hash, expires_at,
         created_at, user_agent)
```

- Password format: `scrypt$16384$8$1$<salt_b64>$<hash_b64>`.
- Session token: `secrets.token_urlsafe(32)`; only `sha256(token)` is stored.
- CSRF token: `secrets.token_urlsafe(24)`; only `sha256(token)` is stored. The raw
  value is also set as a readable `eais_csrf` cookie so the proxy can echo it.
- Cookies: `eais_session` (`HttpOnly`, `SameSite=Lax`, `Secure` in production,
  `Path=/`), `eais_csrf` (readable, same flags minus HttpOnly).

### Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/auth/demo` | public + rate limit | guest session (viewer) |
| `POST` | `/auth/register` | invite code + rate limit | create `user` account |
| `POST` | `/auth/login` | public + rate limit | session for email/password |
| `POST` | `/auth/logout` | cookie (optional) | delete session, clear cookies |
| `GET` | `/auth/me` | viewer | current principal |
| `POST` | `/auth/users` | admin | create an account with any role |

Registration and demo set `Set-Cookie` twice (session + CSRF) and return
`{user, csrf_token}`. `me` returns `{user}` only.

### Admin bootstrap

At startup, if `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set:

1. Validate the email and password length.
2. Hash the password once.
3. Insert the user, or update the existing row's hash/role/active flag.
4. Log the email and role only.

This is intentionally env-as-source-of-truth: a redeploy repairs a deleted or
demoted admin account. It also means a changed environment password takes effect
on restart.

### Frontend

- `lib/auth.ts` — `getMe`, `demoLogin`, `login`, `register`, `logout`; keeps the
  CSRF token in module memory and exposes `csrfHeader()`.
- `lib/api.ts` — adds `credentials: "same-origin"` (or `"include"` in direct
  mode) and the CSRF header; XHR uploads set `withCredentials` in direct mode.
- `components/AuthPanel.tsx` — sign in, create account (invite code), guest, sign
  out; states plainly that products store a hash, not the password.
- `ChatInterface` — bootstraps `me` → else `demo`, shows an account chip, mounts
  the panel, and passes `canUpload`/`canDelete` to `DocumentPanel`: uploads are
  rendered for any signed-in account, deletes only for admins.
- The proxy forwards `cookie`/`set-cookie`, stops sending `BACKEND_API_KEY`, and
  forwards a caller-supplied `X-CSRF-Token`. It must not derive the header from
  the cookie: any request carrying the cookie through the proxy would then pass
  the double-submit check, which is exactly the attack it exists to stop.
  `lib/api.ts` reads `eais_csrf` and sends the header itself.

### Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | empty | Postgres; empty = SQLite at `DATA_DIR/app.db` |
| `SESSION_TTL_HOURS` | `168` | session lifetime |
| `SESSION_SECURE` | env=production | `Secure` cookie flag |
| `INVITE_CODE` | empty | empty = registration disabled |
| `DEMO_LOGIN_ENABLED` | `true` | guest sessions |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | empty | idempotent bootstrap |
| `PASSWORD_MIN_LENGTH` | `8` | registration/login validation |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | login/register/demo bucket |
| `COOKIE_DOMAIN` | empty | leave empty for host-only cookies |

### Testing strategy

| Test | Proves |
| --- | --- |
| `test_demo_creates_guest_session` | FR-007, SC-003 (viewer) |
| `test_register_requires_invite` | FR-008 |
| `test_register_login_me_logout` | FR-009 |
| `test_duplicate_email_is_409` | FR-009 |
| `test_wrong_password_is_generic_401` | FR-009, rate limit |
| `test_csrf_required_for_session_posts` | FR-005 |
| `test_api_key_skips_csrf_and_keeps_working` | FR-006, SC-004 |
| `test_any_signed_in_account_can_upload_but_only_admins_delete` | SC-003 |
| `test_session_token_is_hashed` | FR-004, SC-002 |
| `test_expired_or_inactive_session_is_401` | edge cases |
| `test_admin_bootstrap_is_idempotent` | FR-010 |
| `test_sqlite_still_default` | FR-013 |
| optional `test_postgres_roundtrip` | `TEST_DATABASE_URL` |

### Risks

| Risk | Mitigation |
| --- | --- |
| Admin key leaking through the old proxy | removed from the proxy; guests are created by `/auth/demo` |
| Session fixation | server generates a new token on every login; old sessions are untouched but the cookie is replaced |
| CSRF via `CORS_ORIGINS=*` | double-submit token required for cookie auth; credentials disabled for wildcard origins |
| SQL drift between SQLite and Postgres | one portable statement list, no dialect-only upserts, optional PG integration test |
| Free instance sleeping on a pooled connection | `min_size=0`, short pool timeout, health endpoint fails loudly instead of hiding it |
| Guests bloating the database | expired sessions are purged on each demo/login; guest users with no sessions are removed |
| Losing Postgres credentials | `DATABASE_URL` is `sync: false` in the blueprint; documented in the README |
