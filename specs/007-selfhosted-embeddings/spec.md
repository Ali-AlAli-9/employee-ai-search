# Feature Specification: Self-Hosted Free Embeddings

**Feature Branch**: `007-selfhosted-embeddings`

**Created**: 2026-11-18

**Status**: **Retired / superseded** — the standalone ONNX embedder was removed in favour of the single-service `hashing` + BM25 + LLM design. Kept for historical context only; do not deploy from this spec.

**Input**: The operator asked for a free embedding solution with no external
rate limits, no prepaid token balance, and no per-request pressure. All hosted
API options (Hugging Face router, Gemini, Jina, Cohere, Voyage) enforce either
RPM/TPM quotas or an exhaustible token balance.

## Why

"Free API" is not the same as "unlimited". Hugging Face now returns `402` for
free accounts; Gemini has unpublished per-project limits; Jina gives a finite
free token trial and then requires top-up. Running a small ONNX model inside
our own FastAPI process removes every one of those dependencies: no key, no
billing, no quota, no data leaving the deployment. With a graceful fallback to
the existing hashing embedder, the app still works if the model cannot load on
a memory-constrained host.

## User Scenarios & Testing

### Acceptance scenarios

1. **Given** `EMBEDDING_BACKEND=fastembed`, **When** documents are ingested,
   **Then** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` runs
   locally without prefixes and produces 384-dimensional vectors.
2. **Given** a search query, **When** its embedding is requested, **Then** the
   same local, symmetric model runs without prefixes — no HTTP call to any provider.
3. **Given** the `fastembed` package is missing or the model fails to load,
   **When** the embedder is selected, **Then** the offline hashing embedder is
   used and a warning is logged; the service still starts.
4. **Given** a response vector of the wrong width, **When** vectors are parsed,
   **Then** a `ValueError` asks for re-indexing instead of corrupting the store.
5. **Given** the Docker image is built, **When** the container starts, **Then**
   the model is already in the local cache — no network download at runtime.
6. **Given** `/api/v1/health`, **When** queried, **Then** it reports
   `backend=fastembed`, the model id, and the real dimension.

### Edge cases

- Empty batch → `(0, 384)` matrix, no model call.
- Arabic diacritics/tatweel are still normalised by the shared text pipeline.
- At most one model instance is created per process (singleton `get_embedder`).
- Switching from Gemini (768) to fastembed (384) invalidates existing vectors;
  the docs must require deleting and re-uploading documents.

## Requirements

### Functional

- **FR-001**: Add `FastEmbedEmbedder` to `backend/app/embeddings.py` implementing
  `embed`, `embed_one`, and `dimension`.
- **FR-002**: Use `fastembed.TextEmbedding` with
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (the smallest
  Arabic-capable model actually supported by fastembed 0.9.1: quantised ONNX,
  ~0.22 GB, 384-dim).
- **FR-003**: Use the shared `QUERY_PREFIXES` / `PASSAGE_PREFIXES` maps — empty
  for the symmetric default, `query: ` / `passage: ` when an E5 model is selected;
  normalise returned vectors to unit L2 length.
- **FR-004**: `EMBEDDING_BACKEND=fastembed` MUST select it; any load failure MUST
  fall back to hashing with a warning.
- **FR-005**: Bake the model into the Docker image at build time.
- **FR-006**: Update health, `render.yaml`, `.env.example`, README and
  ARCHITECTURE; keep Gemini/HF backends selectable for operators who want them.

### Non-functional

- No new hosted API dependency and no secret to manage.
- Offline test suite: the `fastembed` import is monkeypatched, so no model is
  downloaded during tests.
- Keep the free Render plan; document the RAM/cold-start trade-off honestly.

## Acceptance checklist

- [X] Tests written first and observed failing.
- [X] Embedder, config, health, requirements, Docker, docs and manifest updated.
- [X] Full backend suite green.
- [X] Single root commit amended and force-pushed to `origin/main`.
