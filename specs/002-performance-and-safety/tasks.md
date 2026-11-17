---
description: "Task list for Performance & Safety (spec 002)"
---

# Tasks: Performance & Safety

**Input**: Design documents from `/specs/002-performance-and-safety/`

**Prerequisites**: plan.md (required), spec.md (required), data-model.md, contracts/

**Tests**: MANDATORY for every user story. Write the test, watch it fail, then
implement.

**Organization**: Tasks are grouped by user story so each can be verified on its
own. Paths are the delivered layout (`backend/app`, `frontend/*`).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1…US5 from spec.md

## Phase 1: Setup

- [X] T001 Add `content_hash` migration + `find_document_by_hash` to
      `backend/app/db.py`
- [X] T002 Add `ratelimit.py` module skeleton and settings in
      `backend/app/config.py`
- [X] T003 Add test environment defaults (`RATE_LIMIT_*`) in
      `backend/tests/conftest.py`

## Phase 2: Foundational (blocks the stories that touch uploads/search)

- [X] T004 Write failing store tests in `backend/tests/test_store.py`
      (round-trip, legacy migration, ranked search, document filter, delete)
- [X] T005 Rewrite `LocalVectorStore` on `.npz` in `backend/app/store.py`;
      add `legacy_vectors_path` to `backend/app/config.py`
- [X] T006 Add a benchmark-style assertion/measurement note for 5,000 vectors
      in `backend/tests/test_store.py` (correctness-gated, timing printed)

**Checkpoint**: Store tests pass; existing retrieval tests still pass.

---

## Phase 3: US1 — Fast vector store (P1) 🎯 MVP

- [X] T007 [US1] Verify `search()` honours `document_ids` with a boolean mask
      and returns descending `(cos+1)/2` scores
- [X] T008 [US1] Verify `upsert` replaces an existing id and `delete_document`
      removes only that document's points
- [X] T009 [US1] Reject embedding-dimension changes with a clear error and mark
      the ingest failed instead of writing mixed vectors

**Independent test**: `pytest backend/tests/test_store.py -q`

---

## Phase 4: US2 — Duplicate uploads (P1)

- [X] T010 [P] [US2] Write failing dedupe tests in
      `backend/tests/test_dedupe.py` (409 + existing id, `replace=true`, failed
      document re-upload, different bytes accepted)
- [X] T011 [US2] Hash upload bytes and return `409` when
      `find_document_by_hash` finds a non-failed document
- [X] T012 [US2] Add `replace: bool = false` query parameter and a shared
      `_remove_document()` helper used by upload-replace and DELETE
- [X] T013 [P] [US2] Surface the conflict in `frontend/lib/api.ts`
      (`DuplicateDocumentError`, `replace` flag)
- [X] T014 [P] [US2] Add the "replace existing copy" action + Arabic/English
      copy in `frontend/components/DocumentPanel.tsx` and `lib/copy.ts`
- [X] T015 [US2] Update `specs/001…/contracts/openapi.yaml` with `replace` and
      `409`
- [X] T015a [US2] Guard ingestion against delete/replace races: skip a deleted
      document and remove partial chunks/vectors after a mid-run deletion or a
      failed ingest (`backend/app/ingestion.py`,
      `backend/tests/test_dedupe.py`)

**Independent test**: `pytest backend/tests/test_dedupe.py -q`

---

## Phase 5: US3 — DOCX page numbers (P2)

- [X] T016 [P] [US3] Write failing page tests in
      `backend/tests/test_docx_pages.py` (explicit break, rendered break, no
      breaks, chunk metadata)
- [X] T017 [US3] Rewrite `_extract_docx` in `backend/app/ingestion.py` to walk
      `w:t`/`w:tab`/`w:cr`/`w:br`/`w:lastRenderedPageBreak` in document order
- [X] T018 [US3] Keep tables on the current page and skip empty pages

**Independent test**: `pytest backend/tests/test_docx_pages.py -q`

---

## Phase 6: US4 — Query cache (P2)

- [X] T019 [P] [US4] Write failing cache tests in `backend/tests/test_cache.py`
      (hit, invalidation after upload/delete, key sensitivity, copy isolation)
- [X] T020 [US4] Wrap `hybrid_search` with a versioned LRU+TTL cache and expose
      `cache_stats()` / `clear_cache()` in `backend/app/search.py`
- [X] T021 [US4] Add `SEARCH_CACHE_SIZE` / `SEARCH_CACHE_TTL_SECONDS` settings

**Independent test**: `pytest backend/tests/test_cache.py -q`

---

## Phase 7: US5 — Rate limit + request tracing (P3)

- [X] T022 [P] [US5] Write failing bucket tests in
      `backend/tests/test_ratelimit.py` (capacity, refill, retry-after, pruning)
- [X] T023 [US5] Implement `TokenBucket`, `RateLimiter`, `rate_limit(scope)`
      dependency in `backend/app/ratelimit.py`
- [X] T024 [US5] Apply the dependency to `/chat`, `/search`,
      `/documents/upload` after the auth dependency
- [X] T025 [P] [US5] Write failing request-id tests in
      `backend/tests/test_request_id.py`
- [X] T026 [US5] Add contextvar + log-record factory + middleware + access log
      in `backend/app/main.py`
- [X] T027 [P] [US5] Forward `X-Forwarded-For` and `X-Request-ID` in
      `frontend/app/api/v1/[...path]/route.ts`
- [X] T028 [US5] Add one HTTP-level test that monkeypatches a low-limit upload
      bucket and asserts `429` + `Retry-After`

**Independent test**: `pytest backend/tests/test_ratelimit.py backend/tests/test_request_id.py -q`

---

## Phase 8: Polish & Cross-Cutting

- [X] T029 [P] Update `README.md` (store format, dedupe, cache, limits,
      tracing, env table)
- [X] T030 [P] Update `.env.example` and `specs/001…/quickstart.md`
- [X] T031 Run `pytest -q` (54 tests) and `tsc --noEmit`; fix regressions
- [X] T032 Run `scripts/evaluate.py` against a seeded local API and confirm the
      harness scores normally (hit@1 1.000 on the sample handbooks, abstention
      correct). The thesis golden set cannot be replayed because `final.docx`
      is not committed; the retrieval/abstention regression tests cover the
      same code paths.
- [X] T033 Commit and push to `origin main`; remind the user to redeploy both
      Render services

## Dependencies

- Phase 2 blocks US1.
- US2 depends on T001 (hash column) and T012 (shared delete helper); the store
  rewrite (US1) is not a hard prerequisite but should land first.
- US3, US4, US5 are independent of each other; US4 depends on the store only at
  runtime.
- Polish runs last.

## Implementation Strategy

Ship US1 + US2 first (direct speed/quality impact), then US3 + US4 (citation
and repeat-query quality), then US5 (hardening). Each phase leaves the suite
green and is independently deployable.

