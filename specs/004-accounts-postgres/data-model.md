# Data Model: Accounts, Sessions and Durable Storage

**Spec**: [`spec.md`](./spec.md) · **Plan**: [`plan.md`](./plan.md)

## Storage selection

| `DATABASE_URL` | Engine | Where the data lives |
| --- | --- | --- |
| empty | SQLite (`sqlite3`, stdlib) | `DATA_DIR/app.db` |
| `postgresql://…` | Postgres (`psycopg` 3 + pool) | the managed database |

`postgres://` is normalised to `postgresql://`. There is no silent fallback: if
the URL is set and unreachable, startup fails loudly instead of splitting
identities between two databases.

## Tables

### `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `email` | TEXT NOT NULL UNIQUE | stored lower-cased |
| `password_hash` | TEXT NOT NULL | `scrypt$n$r$p$salt_b64$hash_b64` |
| `role` | TEXT NOT NULL | `viewer` \| `user` \| `admin` |
| `display_name` | TEXT NULL | optional; never shown as a credential |
| `is_active` | INTEGER NOT NULL | `0` blocks sign-in *and* existing sessions |
| `is_guest` | INTEGER NOT NULL | `1` for `/auth/demo` accounts |
| `created_at` | TEXT NOT NULL | ISO-8601 UTC |
| `last_login_at` | TEXT NULL | updated on `/auth/login` |

Guests use a unique synthetic address (`guest+<uuid>@guest.local`) so the
`UNIQUE` constraint still applies and no real inbox is implied.

### `sessions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `user_id` | TEXT NOT NULL | FK → `users(id)` `ON DELETE CASCADE` |
| `token_hash` | TEXT NOT NULL UNIQUE | `sha256(token)` hex; the raw token is never stored |
| `csrf_hash` | TEXT NOT NULL | `sha256(csrf_token)` hex |
| `expires_at` | TEXT NOT NULL | ISO-8601 UTC, `now + SESSION_TTL_HOURS` |
| `created_at` | TEXT NOT NULL | ISO-8601 UTC |
| `user_agent` | TEXT NULL | first 200 chars, for the operator's logs/UI |

Indexes: `sessions(user_id)`, `sessions(expires_at)`. Expired rows are deleted
at the start of every demo/register/login call.

## Existing tables that gain meaning

`documents.uploaded_by`, `queries.user_id` and therefore `GET /chat/history`
now hold a **stable principal id**:

| Credential | Principal id |
| --- | --- |
| session cookie | `users.id` (UUID) |
| `X-API-Key` | the role name (`admin`, `user`, `viewer`) — unchanged, so scripts keep their old history partition |

No column type changes are required; every id is already `TEXT`.

## In-memory value object

```python
@dataclass(frozen=True)
class Principal:
    id: str                 # users.id or role name for API keys
    role: str               # viewer | user | admin
    kind: str               # "session" | "api_key"
    email: str | None = None
    is_guest: bool = False
```

`require_role(min)` returns a `Principal` and rejects a request when
`ROLE_LEVEL[principal.role] < ROLE_LEVEL[min]`.

## Cookies

| Name | HttpOnly | Readable by JS | Contents |
| --- | --- | --- | --- |
| `eais_session` | yes | no | raw session token (32 random bytes, urlsafe) |
| `eais_csrf` | no | yes | raw CSRF token (24 random bytes, urlsafe) |

Both are `SameSite=Lax`, `Path=/`, `Max-Age = SESSION_TTL_HOURS * 3600` and
`Secure` when `SESSION_SECURE` is on (default: `ENVIRONMENT=production`).
`COOKIE_DOMAIN` is only set when the operator wants a shared parent domain.

## Request flows

### Register / login / demo

```
POST /auth/{demo,register,login}
  -> validate (invite code, email, password, flags)
  -> hash password (register only, scrypt n=2^14 r=8 p=1)
  -> insert user / verify hash / load user
  -> raw_token = token_urlsafe(32); csrf = token_urlsafe(24)
  -> INSERT sessions(token_hash=sha256(raw_token), csrf_hash=sha256(csrf), expires_at)
  -> Set-Cookie: eais_session + eais_csrf
  -> 200 {user, csrf_token}
```

### Authenticated request

```
cookie eais_session ──sha256──▶ sessions row ──▶ users row (is_active, expires_at)
                                                    │
X-API-Key ──────────────────────────────────────────┤
                                                    ▼
                              Principal(kind, id, role, email, is_guest)
                                                    │
             unsafe method + kind=session ──▶ sha256(X-CSRF-Token) == csrf_hash
```

### Logout

`POST /auth/logout` deletes the row matching `sha256(cookie)` when present,
clears both cookies, and answers `204` even without a session.

## Password and token formats

```
password_hash = "scrypt$16384$8$1$" + b64(salt) + "$" + b64(digest)
session token = secrets.token_urlsafe(32)      # only sha256 stored
csrf token    = secrets.token_urlsafe(24)      # only sha256 stored
```

`hmac.compare_digest` is used for password, CSRF and invite-code comparisons.

## Response shapes

`POST /auth/register`, `/auth/login`, `/auth/demo`:

```json
{
  "user": {
    "id": "5f0c…", "email": "a@example.com", "role": "user",
    "display_name": null, "is_guest": false,
    "created_at": "2026-11-15T10:00:00+00:00", "last_login_at": null
  },
  "csrf_token": "…"
}
```

`GET /auth/me`:

```json
{ "user": { "id": "…", "email": "…", "role": "user", "is_guest": false } }
```

No response ever contains `password_hash`, `token_hash`, `csrf_hash` or a raw
session token.

## Error contract

| Status | When |
| --- | --- |
| `400` | malformed email, short password, unknown role |
| `401` | wrong password, unknown email, expired/inactive session, missing credential |
| `403` | registration closed, bad invite code, demo disabled, CSRF missing/mismatched, role too low |
| `409` | email already registered |
| `429` | auth bucket exhausted (`Retry-After`) |
