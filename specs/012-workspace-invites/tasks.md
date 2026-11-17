# Tasks — 012 workspace invites

- [x] T001 Add `workspaces` table, `workspace_id` columns, default backfill and
      scoped DB helpers in `backend/app/db.py`.
- [x] T002 Add `DEFAULT_WORKSPACE_ID` / `DEFAULT_WORKSPACE_NAME` config and
      assign the default workspace in admin bootstrap (`config.py`, `auth.py`).
- [x] T003 Extend `RegisterRequest` with `kind`, `workspace_name`; add workspace
      fields to auth responses; remove `/auth/demo` (`schemas.py`, `auth_api.py`).
- [x] T004 Implement employer/member registration in the identity facade and
      both providers; remove demo providers (`identity/*`).
- [x] T005 Add `Principal.workspace_id` and populate it for sessions/API keys
      (`security.py`).
- [x] T006 Scope all document/chunk/query/user HTTP paths to the principal's
      workspace (`api.py`, `auth_api.py`, `agents.py`, `ingestion.py`,
      `search.py`, `store.py`).
- [x] T007 Replace the auth screen with separate employer/member registration,
      invite URL display and invite-code prefill; remove guest UI/auto-login
      (`AuthView.tsx`, `ChatInterface.tsx`, `auth.ts`, `copy.ts`, `AppShell.tsx`,
      `UsersView.tsx`, `SettingsView.tsx`).
- [x] T008 Update backend/frontend tests for the new model and isolation.
- [x] T009 Run all gates, browser verification, amend + force-push one commit.
