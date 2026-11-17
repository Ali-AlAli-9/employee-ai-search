# Feature Specification: Optional BYOK Chat Hint

**Feature Branch**: `010-optional-byok-chat-hint`

**Created**: 2026-11-19

**Status**: Draft

**Input**: User approval (`نعم اضف`) to add a smart BYOK hint in chat and an
operator-controlled `REQUIRE_CHAT_BYOK` flag. The flag must default to `false`
so free/offline chat, demo guests and the deterministic fallback keep working.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Smart, non-blocking BYOK hint (Priority: P1)

A visitor asks a question and receives a deterministic fallback answer with low
confidence, no evidence, or no citations. The answer is still shown; the UI adds
a short, localized hint that a personal provider key could give a fuller answer,
and one click opens the existing key panel. No key is requested before the free
answer is rendered.

**Why this priority**: it improves discoverability of BYOK without changing the
default product. Free/offline answers remain the normal path and no hosted
quota or model download is introduced.

**Independent Test**: feed the pure hint helper a deterministic low-confidence
result and assert it returns true; then assert it returns false when a model was
used, the answer is well supported, a key is already configured, or BYOK is
disabled.

**Acceptance Scenarios**:

1. **Given** BYOK is enabled and no visitor key is configured, **When** a chat
   answer used the deterministic fallback and has confidence below 0.45,
   **Then** the localized hint appears without replacing the answer.
2. **Given** the same conditions but the fallback returned no citations,
   **When** the stream finishes, **Then** the hint appears.
3. **Given** a provider answered (server or visitor key), **When** confidence is
   low or citations are missing, **Then** no BYOK hint is shown.
4. **Given** a visitor already configured a key or the operator disabled BYOK,
   **When** any answer finishes, **Then** no hint is shown.
5. **Given** the hint is visible, **When** the visitor selects it, **Then** the
   existing key panel opens and the key remains request-scoped/session-only.

---

### User Story 2 - Optional strict chat gate (Priority: P2)

An operator may decide that chat answers must use a real model. With
`REQUIRE_CHAT_BYOK=true`, every non-admin chat request without a visitor key is
refused with the existing `402` key-required contract before the pipeline runs.
The default `false` leaves today's free/offline behavior untouched.

**Why this priority**: it gives the operator a strict deployment option without
making it the public default, which would break demo guests and the zero-cost
promise.

**Independent Test**: set the flag to true and post a non-admin chat request
without `X-LLM-API-Key`; assert `402`, the exact existing detail and the
`X-LLM-Key-Required` header, and assert no provider call or fallback answer.
Repeat as an admin and with a valid visitor key to prove both bypasses.

**Acceptance Scenarios**:

1. **Given** `REQUIRE_CHAT_BYOK=false` and no server LLM key, **When** a non-admin
   chats without a key, **Then** the deterministic answer is still returned.
2. **Given** `REQUIRE_CHAT_BYOK=true` and no server LLM key, **When** a non-admin
   chats without a key, **Then** the API returns `402` with
   `The server API key is reserved for administrators. Add your own provider key to continue.`
3. **Given** strict mode is on, **When** an admin or a key-bearing non-admin
   request chats, **Then** the request proceeds normally.
4. **Given** strict mode is on, **When** the health endpoint is read, **Then**
   `checks.llm_api.require_chat_byok` is `true` so the UI can warn before sending.
5. **Given** strict mode is on or off, **When** a `402` is rendered, **Then** the
   user sees only the existing locally authored copy, never the raw detail.

---

### User Story 3 - Documentation and privacy stay honest (Priority: P3)

The environment example, README, architecture notes and spec-kit task list must
describe the new flag and hint. They must also restate that no provider key is
stored by the server, logged, or sent anywhere except the provider for that one
request.

**Why this priority**: an opt-in flag that is undocumented is an operational
trap; a BYOK feature that appears to persist keys would break the trust model.

**Independent Test**: grep the four documents for `REQUIRE_CHAT_BYOK=false`, the
hint behavior and the request-scoped statement; run the full suites and confirm
the README test counts match the results.

**Acceptance Scenarios**:

1. **Given** a fresh clone, **When** `.env.example` is read, **Then** the new flag
   appears with `false` as its default and a comment explaining the free path.
2. **Given** the README, **When** the configuration table is read, **Then** the
   strict mode and smart hint are documented in English.
3. **Given** `ARCHITECTURE.md`, **When** the BYOK section is read, **Then** the
   request-scoped/no-logging guarantee and the new gate are both present.

### Edge Cases

- An older backend that omits `llm_source` is treated as deterministic so the
  hint can still help; a missing `confidence` must not produce `NaN` behavior.
- A streamed answer with zero citations but high confidence still triggers the
  "insufficient evidence" branch only when the fallback produced it.
- Strict mode must not change search, upload, verify-key, or admin behavior.
- A visitor key rejected by the provider keeps the existing friendly error path;
  the strict gate is about a *missing* key only.
- `LLM_BYOK_ENABLED=false` with strict mode enabled remains an operator choice;
  the UI hides the panel and the API still refuses keyless non-admin chats.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Add `REQUIRE_CHAT_BYOK` to `backend/app/config.py`, parsed with the
  existing boolean helper and defaulting to `false`.
- **FR-002**: In `api._request_llm()`, when the flag is true and the principal is
  not an admin and no visitor key was supplied, raise the existing `402` with
  `SERVER_KEY_ADMIN_ONLY`, the `X-LLM-Key-Required: 1` header, and no pipeline
  execution.
- **FR-003**: When the flag is false, preserve the current decision tree exactly:
  visitor/admin keys pass, no server key means deterministic fallback, and a
  server key means non-admins receive the existing `402`.
- **FR-004**: Publish `require_chat_byok` in `GET /api/v1/health` under
  `checks.llm_api`; keep it a secret-free boolean.
- **FR-005**: Include `llm_source` in the streaming `done` payload and the
  non-streaming chat response so the UI can tell a deterministic answer from a
  model answer without parsing prose.
- **FR-006**: Add a typed pure helper in `frontend/lib/byok-hint.ts` that decides
  whether to show the hint from `llm_source`, confidence, citation count, BYOK
  availability and key state.
- **FR-007**: Add localized hint copy in `frontend/lib/copy.ts` and render a
  non-blocking, clickable notice in `frontend/components/ChatInterface.tsx`.
- **FR-008**: Read `require_chat_byok` from health in the frontend and include it
  in the pre-send keyless-non-admin guard.
- **FR-009**: Keep `LLM_KEY_REQUIRED_DETAIL` and `UNAUTHORISED_DETAIL` byte-for-byte
  unchanged in `frontend/lib/api.ts`; keep all user-facing text locally authored.
- **FR-010**: Update `.env.example`, `README.md`, `ARCHITECTURE.md` and the
  spec-kit task list in the single amended commit.

### Key Entities *(include if feature involves data)*

- **Settings.require_chat_byok**: process-wide operator switch; no new table.
- **DonePayload.llm_source**: `"user"`, `"server"` or `"none"`; backward-compatible
  optional field for older backends.
- **ByokHintInput**: pure frontend decision input; no persisted state.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With default settings, an offline non-admin chat still returns a
  deterministic answer and no `402`.
- **SC-002**: With strict mode on, 100% of keyless non-admin chat requests are
  refused before the orchestrator runs.
- **SC-003**: The hint helper returns true only for unsupported deterministic
  answers, proven by table-driven unit tests in both languages.
- **SC-004**: Backend, frontend tests, type-check and lint all pass with no new
  dependency and no change to the single-commit force-push workflow.

## Assumptions

- The existing `402` contract and `SERVER_KEY_ADMIN_ONLY` string are the single
  source of truth for strict mode; no second error string is introduced.
- `server_key_admin_only` remains `true` in health because the deployment key is
  always an admin privilege, independent of the new flag.
- Visitors accept a session-only key in `sessionStorage`; the server never
  persists or logs it.
- No new service, paid provider, model download, Blueprint or container is added.
