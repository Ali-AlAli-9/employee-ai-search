# Data Model: Supabase Auth and User Administration

**Feature**: `005-supabase-auth-admin` | **Date**: 2026-11-15

## 1. Identity ownership

| Data | Owner | Stored by the platform? |
| --- | --- | --- |
| Email, password hash, confirmation, ban, refresh tokens | Supabase Auth (`auth.users`) | no |
| Session tokens | Supabase (JWT + rotating refresh token) | only inside HttpOnly cookies |
| Role | Supabase `app_metadata.role`, mirrored in `profiles` | mirrored |
| Guest marker | Supabase `is_anonymous` claim, mirrored in `profiles.is_guest` | mirrored |
| Display name | Supabase `user_metadata.display_name` | mirrored |

`user_metadata` is **never** used for authorisation: Supabase lets the user edit
it. Only `app_metadata` (admin-writable) and the mirrored `profiles.role` decide
permissions.

## 2. `profiles` (read model, both dialects)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | equals `auth.users.id` (UUID) |
| `email` | TEXT | lower-cased; null for phone-only accounts |
| `role` | TEXT | `viewer` \| `user` \| `admin` |
| `display_name` | TEXT | nullable |
| `is_guest` | INTEGER | 1 for anonymous users |
| `is_active` | INTEGER | 0 when an admin disabled the account |
| `created_at` | TEXT | ISO-8601 |
| `last_sign_in_at` | TEXT | ISO-8601, nullable |

Indexes: `idx_profiles_email (email)`, `idx_profiles_role (role, is_active)`.

Portable upsert:

```sql
INSERT INTO profiles (...) VALUES (...)
ON CONFLICT (id) DO UPDATE SET
  email = excluded.email, role = excluded.role, ...
```

## 3. Local provider (unchanged, spec 004)

`users` and `sessions` remain exactly as delivered. They are created in every
database (cheap, `IF NOT EXISTS`) but only used when `AUTH_PROVIDER=local`.
This keeps `pytest` offline, the demo zero-setup and the migration additive.

## 4. JWT claims consumed

```json
{
  "sub": "c0ffee00-...",
  "aud": "authenticated",
  "role": "authenticated",
  "exp": 1763200000,
  "iss": "https://project.supabase.co/auth/v1",
  "is_anonymous": false,
  "app_metadata": { "role": "admin", "provider": "email" },
  "user_metadata": { "display_name": "Ali" }
}
```

Mapping:

| Claim | Platform value |
| --- | --- |
| `sub` | `Principal.id` and `profiles.id` |
| `app_metadata.role` | `profiles.role` when in `{viewer,user,admin}`, else `viewer` |
| `is_anonymous` | `profiles.is_guest` / `Principal.is_guest` |
| `email` | `profiles.email` |
| `user_metadata.display_name` | `profiles.display_name` |
| `exp` | access-cookie validity; expiry triggers refresh |

`profiles.is_active` is absent from the JWT, which is why the dependency reads it
on every request: bans and deactivations must not wait for token expiry.

## 5. Lifecycle

```
register (public/invite) ─▶ Admin API create (email_confirm) ─▶ profiles upsert
                                                       └▶ password grant ─▶ cookies
login             ─▶ password grant ─▶ profiles upsert (last_sign_in_at)
demo              ─▶ anonymous signup ─▶ profiles upsert (is_guest=1, viewer)
request           ─▶ verify JWT ─▶ (expired? refresh) ─▶ profile check ─▶ principal
admin update      ─▶ Admin API patch app_metadata/ban ─▶ profiles upsert
admin reset       ─▶ recover(email) ─▶ 202 (no enumeration)
admin delete      ─▶ guests only: Admin API delete ─▶ profiles delete
sync              ─▶ listUsers (paged) ─▶ profiles upsert batch
startup           ─▶ bootstrap admin: create/repair, unban, role=admin
```

## 6. What is never returned

No response body contains `password`, `password_hash`, `access_token`,
`refresh_token`, `csrf_hash`, `SUPABASE_SERVICE_ROLE_KEY` or the JWT secret.
`/auth/me` returns the `profiles` projection only. The service key is used in
server-to-server headers and nowhere else.

## 7. Size and retention

A profile row is ~200 bytes. Guests accumulate because anonymous sign-ins are
permanent Supabase users; the admin panel surfaces them (`include_guests=true`)
and can delete them, and the Supabase dashboard can schedule the documented SQL
cleanup. Sessions are owned by Supabase and expire by project policy.
