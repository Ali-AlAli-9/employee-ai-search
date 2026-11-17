# Plan — 012 workspace invites

## DB contract (shared by all tasks)
`workspace_id` is an optional keyword on all scoped DB functions. `None` = no
filter, so existing tests/ops keep working. HTTP code always passes a concrete id.

New/changed public helpers in `backend/app/db.py`:
- `create_workspace(name, invite_code, owner_id=None)`, `get_workspace(id)`,
  `get_workspace_by_invite(code)`, `default_workspace()`, `public_workspace(ws)`
- scoped: `create_document`, `find_document_by_hash`, `get_document`,
  `list_documents`, `completed_document_ids`, `delete_document`,
  `insert_chunks`, `get_chunks`, `chunks_after`, `all_chunks`, `chunks_version`,
  `delete_chunks_by_document`, `delete_chunks`, `record_query`,
  `list_chat_history`, `create_user`, `get_user`, `get_user_by_email`,
  `update_user`, `delete_user`, `list_users`, `count_active_user_admins`,
  `upsert_profile`, `get_profile`, `list_profiles`, `update_profile`,
  `delete_profile`, `count_active_admins`.
- `all_documents`, `stale_documents`, `document_chunk_counts`, `all_chunk_refs`
  keep `workspace_id=None` as an ops-wide default.

Schema: add `workspaces`, `workspace_id` on `users`, `documents`, `chunks`,
`queries`, `profiles`; backfill default; make `idx_documents_hash_unique`
include `workspace_id`.

## Order
1. DB + config + bootstrap (`db.py`, `config.py`, `auth.py`, `consistency.py`).
2. Auth surface (`schemas.py`, `auth_api.py`, `identity/*`, `security.py`).
3. Data isolation in HTTP/search (`api.py`, `search.py`, `agents.py`,
   `ingestion.py`, `store.py`).
4. Frontend (`AuthView`, `ChatInterface`, `auth.ts`, `copy.ts`, `AppShell`,
   `UsersView`, `SettingsView`, reset page copy).
5. Tests + gates + amend/push.

## Decisions
- Employer = workspace admin; member = `user` (uploads allowed).
- Invite code generated with `secrets.token_urlsafe(12)`, stored raw so it can
  be shown again; rate-limited registration is the abuse control.
- Global `INVITE_CODE` remains as a legacy fallback for member registration.
- No workspace in the URL path; scope comes from the session principal.
- `is_guest` columns and admin "show guests" filter are left in the backend for
  compatibility but no guest is created and the UI no longer exposes them.
