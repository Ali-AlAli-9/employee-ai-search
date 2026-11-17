---
description: "Task list for Self-Hosted Free Embeddings (spec 007)"
---

# Tasks: Self-Hosted Free Embeddings

> **Retired / superseded** by the single-service `hashing` + BM25 + LLM design. Historical only.

**Input**: [`spec.md`](./spec.md) · [`plan.md`](./plan.md)

## Phase 1: Specification

- [X] T001 Write `spec.md` and `plan.md`

## Phase 2: Backend (tests first)

- [X] T002 Write failing tests in `backend/tests/test_embeddings_api.py`
      (symmetric model, optional E5 prefixes, normalisation, width guard,
      empty batch, selection, missing-package fallback, stale-model sanitising)
- [X] T003 Add `FASTEMBED_MODEL`, `FASTEMBED_DIMENSION`, `FASTEMBED_MODELS` and
      backend-aware model/dimension defaults to `config.py`
- [X] T004 Implement `FastEmbedEmbedder` in `backend/app/embeddings.py` and
      select it with a safe fallback in `get_embedder()`
- [X] T005 Add `fastembed` to `backend/requirements.txt`

## Phase 3: Deployment and documentation

- [X] T006 Prefetch the ONNX model into the Docker image at build time
- [X] T007 Update `render.yaml`, `.env.example`, `README.md`, `ARCHITECTURE.md`
      and the health endpoint
- [X] T008 Run the full backend test suite: 196 passed, 1 skipped. Also verified
      the real model locally: `FastEmbedEmbedder`, 384-dim, unit norm.

## Phase 4: Release

- [X] T009 Amend the single root commit and force-push to `origin/main`
- [ ] T010 Verify live health and re-upload documents after Render rebuild

**Independent test**: `py -3 -m pytest backend/tests/test_embeddings_api.py -q`
