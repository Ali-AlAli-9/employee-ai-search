# Implementation Plan: Remote Embedding Service

> **Retired / superseded** by the single-service `hashing` + BM25 + LLM design. Historical only.

## Architecture

```text
browser → Next.js → API (512 MB, no ONNX loaded)
                     │  EMBEDDING_BACKEND=remote
                     │  POST /embed  { texts, task, X-Embed-Key }
                     ▼
              embed service (512 MB, separate service; same account works)
                     │  OnnxEmbedder (Granite 97M ONNX, 384-dim, Arabic)
                     ▼
                 vectors → API → Qdrant + Postgres
```

## Steps

1. **Tests first** (`backend/tests/test_embeddings_api.py`,
   `backend/tests/test_embed_server.py`): batching, auth, retries, dimension
   guard, redaction, config defaults.
2. `config.py`: add remote settings and backend-aware defaults.
3. `embeddings.py`: add `RemoteEmbedder` and select it for `remote`.
4. `ingestion.py`: embed records in `EMBEDDING_BATCH_SIZE` batches.
5. `app/embed_server.py`: minimal authenticated FastAPI wrapper around
   `FastEmbedEmbedder`; lazy model load; 128-text request cap.
6. `backend/Dockerfile.embed`: prefetch model, run embed server. Remove the
   prefetch step from the API Dockerfile so the API image stays light.
7. `render.yaml`, `.env.example`, README, ARCHITECTURE, health reporting.
8. Full backend suite, amend the single root commit, force-push.

## Test mapping

| Test | Requirement |
|---|---|
| `test_remote_embedder_batches_documents` | FR-001, FR-003 |
| `test_remote_embedder_sends_task_and_key` | FR-001, FR-005 |
| `test_remote_embedder_retries_wakeup_502` | scenario 5 |
| `test_remote_embedder_rejects_wrong_dimension` | scenario 6-style guard |
| `test_embed_server_requires_key` | FR-004 / scenario 4 |
| `test_embed_server_caps_batch` | scenario 3 |
| `test_remote_config_defaults` | FR-002 |
