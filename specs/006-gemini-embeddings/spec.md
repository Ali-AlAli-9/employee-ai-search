# Feature Specification: Free-Tier Gemini Embeddings

**Feature Branch**: `006-gemini-embeddings`

**Created**: 2026-11-18

**Status**: Implemented

**Input**: Hugging Face `hf-inference` returned `402` for a free account:
"Inference Providers" now requires purchased credits or a PRO subscription.
The platform must keep trained, Arabic-capable embeddings without paid credits.

## Why

Weights being open does not make hosted inference free. `sentence-transformers`
models are free to download but self-hosting them on the free web instance costs
RAM and slow cold starts. The Gemini Developer API offers `gemini-embedding-001`
on its Free tier at zero token cost, supports 100+ languages including Arabic,
and exposes retrieval-specific task types. It is the smallest change that keeps
real semantic recall without asking the operator to pay Hugging Face.

## User Scenarios & Testing

### Primary user story

As the operator, I set `EMBEDDING_BACKEND=gemini` and a Google AI Studio key.
Uploads and searches work without any paid credits, and `/api/v1/health` shows
the active backend, model, dimension, and only a boolean proving the key reached
the process.

### Acceptance scenarios

1. **Given** `GEMINI_API_KEY` is set, **When** documents are ingested, **Then**
   the API calls `:batchEmbedContents` with `RETRIEVAL_DOCUMENT` and
   `output_dimensionality=768`, one vector per chunk.
2. **Given** a search query, **When** its embedding is requested, **Then** the
   API calls `:embedContent` with `RETRIEVAL_QUERY`, never `RETRIEVAL_DOCUMENT`.
3. **Given** a configured key, **When** a request is made, **Then** the HTTP
   header is `x-goog-api-key: <key>`; the key is never placed in a URL, error
   message, log line, or health response.
4. **Given** a `429` with `Retry-After`, **When** the embedder retries, **Then**
   it waits the requested number of seconds before retrying, at most three
   attempts.
5. **Given** a response whose width is not 768, **When** the vectors are
   parsed, **Then** a `ValueError` asks for re-indexing instead of silently
   corrupting the vector store.
6. **Given** the key is missing or the backend is unknown, **When** the
   embedder is selected, **Then** the offline hashing embedder is used with a
   warning, as for the previous API backend.
7. **Given** an old `EMBEDDING_MODEL` value from the Hugging Face setup,
   **When** `EMBEDDING_BACKEND=gemini`, **Then** the embedder falls back to
   `gemini-embedding-001`/768 with a warning instead of sending an invalid
   model id to Google.

### Edge cases

- Empty text batch → `(0, 768)` matrix, no HTTP call.
- Provider error detail containing the key → key redacted before raising.
- Dimension override explicitly set to another supported width (e.g. 1536) →
  the override is sent as `output_dimensionality` and validated on return.
- `gemini-embedding-2` is intentionally **not** selected: it has no `taskType`
  support and a different (8192-token) prompt format.

## Requirements

### Functional

- **FR-001**: Add `GeminiEmbedder` to `backend/app/embeddings.py` implementing
  `embed`, `embed_query`, `embed_one`, and `dimension`.
- **FR-002**: Document requests MUST use `POST
  /v1beta/models/{model}:batchEmbedContents`; query requests MUST use `POST
  /v1beta/models/{model}:embedContent`.
- **FR-003**: Requests MUST carry `x-goog-api-key`, `RETRIEVAL_DOCUMENT` or
  `RETRIEVAL_QUERY`, `models/{model}`, and `output_dimensionality`.
- **FR-004**: Returned vectors MUST be L2-normalised float32.
- **FR-005**: `EMBEDDING_BACKEND=gemini` MUST be selectable via environment
  variables; a missing key MUST fall back to hashing.
- **FR-006**: `/api/v1/health` MUST report `gemini_api_key_configured` as a
  boolean and MUST NOT expose the key.
- **FR-007**: Changing backend/model/dimension MUST still require deleting and
  re-uploading documents; documentation must say so.

### Non-functional

- Keep the offline test suite network-free: all HTTP calls are monkeypatched.
- Keep the existing `hf-api` backend selectable for operators who do have
  credits; no silent removal of functionality.
- No new Python dependency: `httpx` is already used.

## Acceptance checklist

- [X] Tests written first and observed failing.
- [X] Backend, config, health, docs, and deployment manifest updated.
- [X] Full backend suite green.
- [X] Single root commit amended and force-pushed to `origin/main`.
