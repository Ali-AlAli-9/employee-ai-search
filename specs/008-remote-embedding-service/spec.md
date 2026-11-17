# Feature Specification: Remote Embedding Service (spec 008)

> **Retired / superseded.** The two-service remote embed worker, its Dockerfile,
> `embed_server.py` and all `EMBEDDING_URL` / `EMBEDDING_API_KEY` settings were removed.
> The hosted deployment now uses one API service with offline `hashing` embeddings,
> BM25 retrieval and the LLM for answer quality. This document is historical only.

**Purpose**: Move the self-hosted ONNX embedding model out of the free Render API
process and into a dedicated free Render service (the same account works; a second
account is optional), so the API stays below the 512 MB free-plan limit while
embeddings remain free, unlimited, private and quota-free.

## User scenarios

1. **Given** the API runs on Render's 512 MB free plan, **When** a document is
   uploaded, **Then** the API never loads an ONNX model into its own process.
2. **Given** a separate Render service in the same account (or a second account),
   **When** the embedding service is deployed, **Then** it holds the quantised
   Arabic-capable MiniLM model in its own 512 MB container and exposes an
   authenticated `POST /embed` endpoint.
3. **Given** `EMBEDDING_BACKEND=remote`, **When** documents are indexed or a query
   is searched, **Then** the API sends batches of plain text to the embedding
   service and receives 384-dimensional unit vectors.
4. **Given** a missing or wrong `X-Embed-Key`, **When** `/embed` is called,
   **Then** the service answers `401` without echoing the key.
5. **Given** the embedding service is asleep or briefly returns `502/503/504`,
   **When** the API embeds a batch, **Then** it retries with backoff before
   surfacing an error; no key or document text appears in logs.
6. **Given** `/api/v1/health`, **When** queried, **Then** it reports
   `backend=remote`, the configured model, dimension and a
   `remote_service_configured` boolean — never the shared secret or full URL.

## Requirements

- **FR-001**: Add `RemoteEmbedder` selected by `EMBEDDING_BACKEND=remote`.
- **FR-002**: Add `EMBEDDING_URL`, `EMBEDDING_API_KEY` and
  `EMBEDDING_BATCH_SIZE` settings; default model/dimension follow the small
  multilingual Granite 97M ONNX model (384). The batch default is 8 and the
  client caps stale higher overrides, because 32/64-text batches measured
  ~493/~764 MB peak RSS and were killed on the free plan.
- **FR-003**: Batch document embedding in the ingestion pipeline so no single
  HTTP payload or vector array holds the whole document. Inputs are truncated to
  256 tokens (the configured chunk size), keeping peak RSS near ~330 MB.
- **FR-004**: Provide `backend/Dockerfile.embed` and `app/embed_server.py` for a
  standalone FastAPI service that prefetches the quantised ONNX graph and
  tokenizer at image build time and loads them with a memory-bounded ONNX Runtime
  session. The worker rejects batches above 8 texts with a 400 instead of
  exhausting the 512 MB free-plan container.
- **FR-005**: Keep legacy `granite` (in-process ONNX), `fastembed` (older in-process
  MiniLM), `gemini`, `hf-api` and `hashing` backends selectable; `remote` becomes
  the hosted default.
- **FR-006**: Document the two-service deployment in README and ARCHITECTURE.

## Out of scope

- Billing/upgrade automation.
- Moving Supabase Postgres or Qdrant to another account.
- Changing the exact `LLM_KEY_REQUIRED_DETAIL` string in the frontend.
