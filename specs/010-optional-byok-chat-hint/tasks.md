---
description: "Task list for Optional BYOK Chat Hint (spec 010)"
---

# Tasks: Optional BYOK Chat Hint

**Input**: [`spec.md`](./spec.md) · [`plan.md`](./plan.md)

**Prerequisites**: plan.md (required), spec.md (required)

## Phase 1: Specification

- [X] T001 Write `spec.md` and `plan.md`

## Phase 2: User Story 1 - Smart BYOK hint (Priority: P1) 🎯 MVP

**Goal**: weak deterministic answers offer BYOK without blocking or replacing the
free answer.

**Independent Test**: `npm.cmd test -- byok-hint.test.ts`

### Tests first (must fail before implementation)

- [X] T002 [US1] Add `frontend/lib/byok-hint.test.ts` with deterministic
      low-confidence, no-citation, model-answer, key-configured, BYOK-disabled and
      missing-source cases.

### Implementation

- [X] T003 [US1] Add typed `shouldSuggestByok()` to `frontend/lib/byok-hint.ts`
- [X] T004 [US1] Add `byokHint` copy to `frontend/lib/copy.ts` in English and Arabic
- [X] T005 [US1] Add optional `llm_source` to `DonePayload` in
      `frontend/lib/types.ts` and include it in the SSE done payload in
      `backend/app/api.py` via `PipelineResult.llm_source` (`backend/app/agents.py`)
- [X] T006 [US1] Render a clickable, non-blocking hint in
      `frontend/components/ChatInterface.tsx` that opens `LlmKeyPanel`
- [X] T007 [US1] Run the focused frontend test green

## Phase 3: User Story 2 - Optional strict chat gate (Priority: P2)

**Goal**: an operator can require a visitor key for all non-admin chats without
changing the default.

**Independent Test**: `py -3 -m pytest backend/tests/test_byok.py -q`

### Tests first (must fail before implementation)

- [X] T008 [US2] Extend `backend/tests/test_byok.py` with default false, strict
      keyless rejection/exact detail/header, admin and visitor-key bypass,
      offline default behavior, and health flag cases.

### Implementation

- [X] T009 [US2] Add `REQUIRE_CHAT_BYOK` to `backend/app/config.py`
- [X] T010 [US2] Factor the existing 402 into a helper and enforce strict mode in
      `api._request_llm()` only
- [X] T011 [US2] Publish `require_chat_byok` in `GET /api/v1/health`
- [X] T012 [US2] Add `require_chat_byok` to `HealthChecks` and extend the pre-send
      guard in `frontend/components/ChatInterface.tsx`
- [X] T013 [US2] Run the focused backend test green

## Phase 4: User Story 3 - Documentation and privacy (Priority: P3)

**Goal**: the new switch and hint are documented and the key boundary is unchanged.

- [X] T014 [US3] Add `REQUIRE_CHAT_BYOK=false` to `.env.example`
- [X] T015 [US3] Update `README.md` config table, behavior notes and test counts
- [X] T016 [US3] Update `ARCHITECTURE.md` BYOK/gate section

## Phase 5: Verification and release

- [X] T017 Run `py -3 -m pytest tests -q` from `backend/`
- [X] T018 Run `npm.cmd test`, `npm.cmd run type-check`, `npm.cmd run lint` from
      `frontend/`
- [X] T019 Amend the single root commit and force-push to `origin/main`
- [ ] T020 Operator-only from spec 009 remains pending: run the consistency
      commands after Render rebuild with the API environment

**Independent test per story**: see the `Independent Test` line in each phase.
