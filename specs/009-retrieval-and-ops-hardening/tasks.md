---
description: "Task list for Retrieval & Operational Hardening (spec 009)"
---

# Tasks: Retrieval & Operational Hardening

**Input**: [`spec.md`](./spec.md) · [`plan.md`](./plan.md)

**Prerequisites**: plan.md (required), spec.md (required)

## Phase 1: Specification

- [X] T001 Write `spec.md` and `plan.md`

## Phase 2: User Story 1 - Per-document retrieval (Priority: P1) 🎯 MVP

**Goal**: every completed document gets its own retrieval attempt and the hits
are merged fairly.

**Independent Test**: `py -3 -m pytest backend/tests/test_per_document_retrieval.py -q`

### Tests first (must fail before implementation)

- [X] T002 [US1] Add `backend/tests/test_per_document_retrieval.py`: one search
      per document, one embedding call, explicit document subset, score merge and
      dedup, and `agents.retrieve()` wiring.

### Implementation

- [X] T003 [US1] Add `PER_DOCUMENT_TOP_K` to `backend/app/config.py` and
      `.env.example`
- [X] T004 [US1] Add precomputed `query_vector` support and
      `per_document_search()` to `backend/app/search.py`
- [X] T005 [US1] Switch `agents.retrieve()` to the new function while keeping
      the text dedup and trace shape
- [X] T006 [US1] Run the focused test file green

## Phase 3: User Story 2 - Consistency tooling (Priority: P2)

**Goal**: operator can see and, only with explicit opt-in, repair disagreement
between document rows, chunk rows and vectors.

**Independent Test**: `py -3 -m pytest backend/tests/test_consistency.py -q`

### Tests first (must fail before implementation)

- [X] T007 [US2] Add `backend/tests/test_consistency.py` with count mismatch,
      orphan chunk/vector, stale processing, dry-run and apply cases.

### Implementation

- [X] T008 [US2] Add `all_points()` and `delete_points()` to both store adapters
      in `backend/app/store.py`
- [X] T009 [US2] Add reporting/reconcile helpers and DB queries in
      `backend/app/db.py` and `backend/app/consistency.py`
- [X] T010 [US2] Add `scripts/verify_consistency.py` and
      `scripts/reconcile_documents.py`
- [X] T011 [US2] Run the focused test file green

## Phase 4: User Story 3 - Account protection (Priority: P3)

**Goal**: account-keyed lockout plus correct proxy client identity.

**Independent Test**: `py -3 -m pytest backend/tests/test_account_lockout.py backend/tests/test_ratelimit.py -q`

### Tests first (must fail before implementation)

- [X] T012 [US3] Add `backend/tests/test_account_lockout.py`; extend
      `backend/tests/test_ratelimit.py` with the trusted last-hop case.

### Implementation

- [X] T013 [US3] Add `TRUST_PROXY_HEADERS` and lock settings to `config.py`
- [X] T014 [US3] Add `login_attempts` schema and helpers to `db.py`, and fix
      `ratelimit.client_ip()`
- [X] T015 [US3] Wire the lock into `auth_api.login()` without changing the
      friendly-error contract in the frontend
- [X] T016 [US3] Run the focused tests green

## Phase 5: User Story 4 - Documentation truth (Priority: P4)

**Goal**: docs match code.

- [X] T017 [US4] Fix the 19→26 frontend test count in `README.md`
- [X] T018 [US4] Fix the "upload (multipart, admin)" line in
      `ARCHITECTURE.md` to say any signed-in account uploads, admins delete or
      replace others' documents
- [X] T019 [US4] Document new config keys, lockout defaults and both operator
      commands in `README.md` and `.env.example`

## Phase 6: Verification and release

- [X] T020 Run `py -3 -m pytest tests -q` from `backend/`
- [X] T021 Run `npm.cmd test`, `npm.cmd run type-check`, `npm.cmd run lint`
      from `frontend/`
- [X] T022 Amend the single root commit and force-push to `origin/main`
- [ ] T023 Operator, not agent, runs the new commands against the live database
      after the rebuild

**Independent test per story**: see the `Independent Test` line in each phase.
