---
description: "Task list for Remote Embedding Service (spec 008)"
---

# Tasks: Remote Embedding Service

> **Retired / superseded** by the single-service `hashing` + BM25 + LLM design. Historical only.

**Input**: [`spec.md`](./spec.md) · [`plan.md`](./plan.md)

## Phase 1: Specification

- [X] T001 Write `spec.md` and `plan.md`

## Phase 2: Tests first

- [X] T002 Write failing tests for `RemoteEmbedder`, config, batching, retries,
      redaction and the standalone embed server

## Phase 3: Implementation

- [X] T003 Add remote settings/backend-aware defaults to `config.py`
- [X] T004 Implement `RemoteEmbedder` and select it in `get_embedder()`
- [X] T005 Batch embeddings in `ingestion.py`
- [X] T006 Implement `app/embed_server.py` and `backend/Dockerfile.embed`
- [X] T007 Update API Dockerfile, `render.yaml`, `.env.example`, README,
      ARCHITECTURE and health reporting

## Phase 4: Release

- [X] T008 Run the full backend suite: 208 passed, 1 skipped
- [X] T009 Amend the single root commit and force-push to `origin/main`
- [ ] T010 Deploy the embed service as a separate service in the same account
      (a second account is optional), re-upload documents and run the evaluation
      harness
