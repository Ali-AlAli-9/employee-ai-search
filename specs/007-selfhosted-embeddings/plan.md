# Implementation Plan: Self-Hosted Free Embeddings

> **Retired / superseded** by the single-service `hashing` + BM25 + LLM design. Historical only.

**Spec**: [`spec.md`](./spec.md) · **Branch**: `007-selfhosted-embeddings` ·
**Date**: 2026-11-18

## Technical approach

One more implementation of the existing embedder interface. Ingestion and
search already call `embed()` for documents and `embed_one()` for queries, so
neither changes.

```
ingestion → embedder.embed(chunks)  → TextEmbedding.embed(chunks)
search    → embedder.embed_one(q)   → TextEmbedding.embed([q])
                         │
                         └─ local ONNX inference → L2-normalise → (N, 384) float32
```

`fastembed` is used instead of plain `sentence-transformers` because its
quantised ONNX model is ~4x smaller and needs a fraction of the RAM, which
matters on the free 512 MB Render instance.

### Configuration rules

| Variable | Behaviour |
| --- | --- |
| `EMBEDDING_BACKEND=fastembed` | Select `FastEmbedEmbedder` when the package/model load |
| `EMBEDDING_MODEL` | Defaults to `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` for this backend |
| `EMBEDDING_DIMENSION` | Defaults to 384 for this backend; explicit override wins |
| `FASTEMBED_CACHE_PATH` | Set by the Dockerfile; reused by the runtime process |

### Failure policy

Import errors and model-load errors are caught in `get_embedder()`, logged with
`logger.warning`, and downgraded to `HashingEmbedder`. There is no crash path.
A wrong-width result is *not* silently accepted — it raises `ValueError` so the
operator must re-index.

### Testing strategy

| Test | Proves |
| --- | --- |
| `test_documents_have_no_prefix_for_symmetric_model` | FR-003 |
| `test_query_has_no_prefix_for_symmetric_model` | FR-003 |
| `test_e5_models_still_get_asymmetric_prefixes` | FR-003 |
| `test_vectors_are_normalised_and_wrong_width_rejected` | FR-003, guard |
| `test_missing_package_falls_back_to_hashing` | FR-004 |
| `test_fastembed_backend_is_selected` | FR-004 |
| `test_empty_batch_makes_no_model_call` | edge case |

All model calls are monkeypatched; no ONNX download happens in CI.

### Deployment

`backend/Dockerfile` sets `FASTEMBED_CACHE_PATH=/app/.cache/fastembed`, prefetches
the model during `docker build`, and chowns the cache for the non-root user.
`render.yaml` switches the API service to `fastembed`/384 and drops the now
unused Gemini key variable. Docs keep Gemini and `hf-api` as optional backends
and repeat the re-index warning when switching between 768 and 384 dimensions.

### Rollout

1. Write tests, run them, confirm failure.
2. Implement config, embedder, selection, health, requirements, Docker, docs.
3. Run `py -3 -m pytest backend/tests -q`.
4. Amend the single root commit and force-push to `origin/main`.
5. Render rebuilds the image; verify health shows `fastembed` and then
   re-upload documents before running `scripts/evaluate.py`.
