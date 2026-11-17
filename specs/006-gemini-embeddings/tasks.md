---
description: "Task list for Free-Tier Gemini Embeddings (spec 006)"
---

# Tasks: Free-Tier Gemini Embeddings

**Input**: [`spec.md`](./spec.md) · [`plan.md`](./plan.md)

## Phase 1: Specification

- [X] T001 Write `spec.md` and `plan.md`

## Phase 2: Backend (tests first)

- [X] T002 Write failing tests in `backend/tests/test_embeddings_api.py`
      (wire format, task types, header, normalisation, retry, width guard,
      key redaction, selection/fallback, health boolean)
- [X] T003 Add `GEMINI_API_KEY`, `GEMINI_EMBEDDING_MODEL`, Gemini dimension
      defaults, backend-aware model/dimension helpers and health flag
- [X] T004 Implement `GeminiEmbedder` in `backend/app/embeddings.py`
- [X] T005 Select `GeminiEmbedder` in `get_embedder()` with safe fallbacks

## Phase 3: Deployment and documentation

- [X] T006 Update `render.yaml` and `.env.example`
- [X] T007 Update `README.md` and `ARCHITECTURE.md`
- [X] T008 Run the full backend test suite: 186 passed, 1 skipped

## Phase 4: Release

- [X] T009 Amend the single root commit and force-push to `origin/main`
- [ ] T010 Verify live health and re-upload documents after Render redeploy

**Independent test**: `py -3 -m pytest backend/tests/test_embeddings_api.py -q`
