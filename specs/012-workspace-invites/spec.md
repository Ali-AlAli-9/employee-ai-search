# 012 — Workspace invites and guest removal

## Goal
Move the product from an open demo to a two-path account model: an employer
registers a workspace and receives a reusable invite link/code; employees
register through that link and join the workspace. Guests are removed entirely.
Every document, chunk, query and user list is isolated per workspace.

## User stories
1. As an employer I register with a workspace name and receive an invite code
   and an invite URL I can share. I am the admin of my workspace.
2. As an employee I open the invite link (`/auth?invite=CODE`); the invite code is
   prefilled, I register, and I join that workspace as a normal user.
3. As a user with no invite code I cannot register; I must sign in or ask my
   employer for an invite. There is no guest/demo session anywhere.
4. As a member of workspace A I can never see, search, cite, replace or delete
   documents from workspace B, even if I know a document id.
5. As a workspace admin I manage only the users of my workspace.

## Functional requirements
- `POST /api/v1/auth/register` accepts `kind: "employer" | "member"`,
  `workspace_name` (employer only) and `invite_code` (member only).
- Employer registration creates a `workspaces` row with a generated invite code
  and returns `workspace: {id, name, invite_code, invite_url}` in the session
  response. The creator's role is `admin`.
- Member registration requires a valid workspace invite code; role is `user`.
  A configured global `INVITE_CODE` remains a legacy fallback only.
- `POST /api/v1/auth/demo` is removed. `DEMO_LOGIN_ENABLED` is no longer read.
  No `is_guest` row is ever created. `is_guest` columns stay for compatibility.
- `Principal` carries `workspace_id`; API keys resolve to the default workspace.
- Every document/chunk/query/user query accepts an optional `workspace_id`
  filter. `None` means "no filter" (legacy ops/tests); HTTP callers always pass
  the principal's workspace, so isolation is enforced at the API boundary.
- The corpus cache and vector payloads include `workspace_id`.
- Backfill: a default workspace is created on startup; pre-existing rows that
  have no `workspace_id` are assigned to it.
- `users.email` stays globally unique (MVP decision).
- The existing `402` LLM-key contract, `REQUIRE_CHAT_BYOK=false`,
  `LLM_KEY_REQUIRED_DETAIL`, friendly errors and `/PageLabels` rules are unchanged.

## Out of scope
- Per-document ACLs, SSO, invite expiry, invite revocation, email sending.
- Changing retrieval algorithms, eval set, deployment or Render config.

## Success criteria
- Backend suite green; frontend suite green; type-check, lint, build green.
- Browser check: employer registers, invite URL shown; member registers from the
  link in a clean context; guest/demo button absent; cross-workspace document id
  returns 404 and search shows no foreign chunk.
- Single amended commit, `origin/main` matching, commit count remains 1.
