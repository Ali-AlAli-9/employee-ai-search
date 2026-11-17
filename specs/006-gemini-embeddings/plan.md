# Implementation Plan: Free-Tier Gemini Embeddings

**Spec**: [`spec.md`](./spec.md) · **Branch**: `006-gemini-embeddings` ·
**Date**: 2026-11-18

## Technical approach

Add one more implementation of the existing embedder interface. Nothing in
ingestion, search, or the vector store changes: they already call `embed()` for
documents and `embed_one()` for queries.

```
ingestion → embedder.embed(chunks)  → :batchEmbedContents (RETRIEVAL_DOCUMENT)
search    → embedder.embed_one(q)   → :embedContent        (RETRIEVAL_QUERY)
                         │
                         └─ httpx.post → L2-normalise → (N, 768) float32
```

### Wire format

Single request body:

```json
{
  "model": "models/gemini-embedding-001",
  "taskType": "RETRIEVAL_QUERY",
  "output_dimensionality": 768,
  "content": { "parts": [{ "text": "كم يوم إجازة؟" }] }
}
```

Batch body:

```json
{
  "requests": [
    {
      "model": "models/gemini-embedding-001",
      "taskType": "RETRIEVAL_DOCUMENT",
      "output_dimensionality": 768,
      "content": { "parts": [{ "text": "annual leave policy" }] }
    }
  ]
}
```

Header: `x-goog-api-key: <GEMINI_API_KEY>`. The key is never interpolated into
the URL. `gemini-embedding-001` requires manual normalisation for non-3072
widths, which the shared matrix code already performs.

### Configuration rules

| Variable | Behaviour |
| --- | --- |
| `EMBEDDING_BACKEND=gemini` | Select `GeminiEmbedder` when a key exists |
| `GEMINI_API_KEY` | Secret; presence only is reported by health |
| `EMBEDDING_MODEL` | Defaults to `gemini-embedding-001` for this backend; an old HF value is replaced with a warning |
| `EMBEDDING_DIMENSION` | Explicit override wins; otherwise 768 for Gemini |

The `hf-api` path stays intact. Unknown backends keep falling back to hashing.

### Error handling

- Retry `429/500/502/503/504` up to three attempts, honouring `Retry-After`
  (capped at 10 s), matching the HF embedder.
- On `>=400`, parse a short detail string and redact the API key before raising.
- Reject any response whose vector width differs from the configured dimension.

### Testing strategy

| Test | Proves |
| --- | --- |
| `test_gemini_model_defaults_to_free_tier_dimension` | FR-005, config default |
| `test_documents_use_batch_endpoint_document_task_and_key_header` | FR-002/003/004 |
| `test_query_uses_embed_content_and_query_task` | FR-002 |
| `test_rate_limit_is_retried_with_retry_after` | retry rule |
| `test_unexpected_dimension_is_rejected` | FR-004, corrupt index guard |
| `test_provider_error_does_not_echo_api_key` | FR-003 |
| `test_missing_gemini_key_falls_back_to_hashing` | FR-005 |
| `test_gemini_key_selects_gemini_embedder` | FR-005 |
| `test_health_reports_gemini_key_presence_without_the_secret` | FR-006 |

All provider calls are monkeypatched, so no key or network is needed to run the
suite.

### Documentation and deployment

Update `.env.example`, `render.yaml`, `README.md`, and `ARCHITECTURE.md` so the
default hosted deployment uses Gemini. Keep the explicit warning that switching
backend/model/dimension invalidates existing vectors.

### Rollout

1. Run the new tests and confirm they fail before implementation.
2. Implement config, embedder, selection, and health.
3. Run `py -3 -m pytest backend/tests -q`.
4. Amend the single root commit and force-push to `origin/main`.
5. Set the four Render API-service variables in the dashboard (dashboard values
   override `render.yaml`), redeploy, verify health, then re-upload documents.
