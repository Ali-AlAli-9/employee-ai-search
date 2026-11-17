# Implementation Plan: Optional BYOK Chat Hint

**Branch**: `010-optional-byok-chat-hint` | **Date**: 2026-11-19 |
**Spec**: [`spec.md`](./spec.md)

**Input**: [`spec.md`](./spec.md)

## Summary

Add one opt-in backend switch and one non-blocking frontend suggestion to the
existing single-service app. `REQUIRE_CHAT_BYOK=false` keeps the free/offline
deterministic path exactly as it is. When enabled, the existing `402`
key-required contract is applied earlier to every keyless non-admin chat. A new
`llm_source` field on the chat result lets the UI suggest BYOK only when the
built-in fallback produced a weak or unsupported answer.

## Technical Context

**Language/Version**: Python 3.11+, mypy-style hints; TypeScript 5 strict

**Primary Dependencies**: existing FastAPI backend and Next.js 14 frontend; no
new runtime or test dependency

**Storage**: none. The flag is environment configuration; BYOK remains a
request header and an optional `sessionStorage` entry in the browser.

**Testing**: `py -3 -m pytest tests -q`; `npm.cmd test`, `npm.cmd run
type-check`, `npm.cmd run lint`

**Target Platform**: one Linux container on Render free tier (512 MB)

**Project Type**: web service + React client

**Performance Goals**: strict rejection happens before search or any provider
call; hint evaluation is a pure synchronous function

**Constraints**: free/offline default, no hosted embedding quota, no model
download, one API service, manual Render Web Service (no Blueprint), exact
`LLM_KEY_REQUIRED_DETAIL` literal, friendly user-facing errors only, BYOK
request-scoped and never stored/logged

**Scale/Scope**: one config field, two response fields, one pure frontend helper,
one UI notice, four documentation files

## Constitution Check

*Gates from `specs/001-employee-ai-search-platform/constitution.md`.*

| Principle | Status | Note |
|---|---|---|
| Test-Driven Development | PASS | Config default, strict gate, health flag and hint helper all get failing tests first |
| Code Quality / type hints | PASS | Typed helper and optional response field; existing lint/type-check gates remain |
| Security by default | PASS | Strict mode is opt-in, uses the existing 402 contract and never stores a key |
| Observability & reliability | PASS | Health publishes the flag; `llm_source` avoids parsing prose to detect fallback |
| Documentation as code | PASS | README, ARCHITECTURE, `.env.example` and tasks updated in the same commit |
| Free-tier budget | PASS | No new service, model, provider or dependency; default path unchanged |

No constitution violation, so no complexity-tracking exception is needed.

## Project Structure

```text
backend/app/
├── config.py      # REQUIRE_CHAT_BYOK (default false)
├── api.py         # strict gate, health flag, llm_source in responses
└── agents.py      # PipelineResult.llm_source
backend/tests/
├── test_byok.py               # strict mode, default path, admin/BYOK bypass, health
└── test_api.py                # llm_source in non-stream/stream responses
frontend/lib/
├── api.ts         # HealthChecks.require_chat_byok
├── types.ts       # DonePayload.llm_source (optional)
├── byok-hint.ts   # new pure decision helper
└── byok-hint.test.ts
frontend/components/
├── ChatInterface.tsx          # consume health flag and render hint
└── ChatInterface.test.tsx?    # only if a stable render harness is practical
frontend/lib/copy.ts           # localized hint copy
.env.example · README.md · ARCHITECTURE.md
specs/010-optional-byok-chat-hint/{spec,plan,tasks}.md
```

**Structure Decision**: keep the existing flat backend/app and frontend/lib
layout. The hint decision is extracted into a pure module so it is testable
without mounting the whole chat component.

## Technical Approach

### 1. Backend strict gate

`_request_llm(principal, provided)` gains an early check after the existing
admin/provided fast path:

```python
if settings.require_chat_byok:
    raise _key_required()
```

The helper `_key_required()` centralises the existing `402`, detail string and
`X-LLM-Key-Required` header so strict mode and server-key mode cannot drift.
When the flag is false, the remaining branches are byte-for-byte equivalent to
today's behavior.

### 2. Answer provenance

`Orchestrator._run()` already records `llm_source` in `trace`; copy it onto a new
`PipelineResult.llm_source` field with a `"none"` default. `api.chat()` includes
it in the SSE `done` payload and the non-streaming JSON response. Older frontends
ignore the extra field; older backends simply omit it, which the frontend treats
as deterministic.

### 3. Frontend hint

`shouldSuggestByok()` returns false unless BYOK is available and no key is
configured. It then returns true only when the source is deterministic (or
absent for an older backend) **and** either confidence is below `0.45` or there
are no citations. `ChatInterface` counts citations during the stream, calls the
helper on `onDone`, and renders a localized amber notice with a button that
opens `LlmKeyPanel`. The answer itself is never replaced.

### 4. Frontend strict guard

Health parsing adds `requireChatByok`. The existing pre-send keyless guard is
extended from `serverLlm` to `serverLlm || requireChatByok`, still limited to
non-admins and still using `copy.llmKeyNeeded`. A `402` from an older backend or
a race remains handled by `chatStream` and `friendlyError`.

### 5. Documentation

`.env.example` documents the default and its cost impact. README documents the
flag, hint and updated test counts. ARCHITECTURE documents the earlier gate,
the health flag and the unchanged "never stored/logged" boundary.

## Testing Strategy

| Test | Proves |
|---|---|
| `test_require_chat_byok_defaults_to_false` | FR-001 and free default |
| `test_strict_mode_refuses_keyless_non_admin_chat` | FR-002, SC-002 |
| `test_strict_mode_allows_admin_and_visitor_key` | FR-002 acceptance bypasses |
| `test_default_mode_keeps_offline_fallback` | FR-003, SC-001 |
| `test_health_reports_require_chat_byok` | FR-004 |
| `test_chat_response_reports_llm_source` | FR-005 |
| `shouldSuggestByok` table tests | FR-006, FR-007, SC-003 |
| Literal-preservation tests in `api.test.ts` | FR-009 |
| Full backend/frontend gates | SC-004 |

## Rollout

1. Write the spec-kit documents.
2. Write focused failing tests for backend and frontend.
3. Implement backend configuration, gate, health flag and provenance field.
4. Implement the frontend helper, copy, health flag and notice.
5. Run focused tests, then all four full gates.
6. Update README counts and amend the single root commit; force-push to
   `origin/main`.
