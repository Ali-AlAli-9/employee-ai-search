# Data Model: Performance & Safety

**Feature**: `002-performance-and-safety` | **Date**: 2026-11-15

## Document (SQLite `documents`)

| Column | Type | Change | Notes |
|---|---|---|---|
| `id` | TEXT PK | — | UUID |
| `filename` | TEXT | — | original name |
| `stored_filename` | TEXT | — | sanitised name |
| `content_type` | TEXT | — | MIME |
| `size_bytes` | INTEGER | — | upload size |
| `status` | TEXT | — | pending / processing / completed / failed |
| `chunks_count` | INTEGER | — | populated on completion |
| `error_message` | TEXT NULL | — | failure reason |
| `uploaded_by` | TEXT | — | role |
| `created_at` / `updated_at` | TEXT | — | ISO-8601 UTC |
| `completed_at` | TEXT NULL | — | ISO-8601 UTC |
| **`content_hash`** | **TEXT NULL** | **new** | hex `sha256` of the uploaded bytes |

**Indexes**

```sql
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_hash_unique
    ON documents(content_hash)
    WHERE content_hash IS NOT NULL AND status != 'failed';
```

**Migration** (runs in `db.init_db()` for every startup):

1. `PRAGMA table_info(documents)`; if `content_hash` is missing, run
   `ALTER TABLE documents ADD COLUMN content_hash TEXT`.
2. Create both indexes (idempotent).
3. Existing rows keep `NULL`, so old data is never considered a duplicate.

**Rules**

- A hash matches only documents whose `status != 'failed'` (a failed ingest can
  be retried).
- Inserting a hash that already exists raises `sqlite3.IntegrityError`, mapped
  to `409` (concurrent-upload safety).
- Deleting a document removes its chunks (FK cascade) and its vectors.

## VectorPoint (`data/vectors.npz`)

`numpy.savez` archive (uncompressed float32 for fast `np.load`), written to
`vectors.npz.tmp` then atomically moved:

| Array | dtype | Shape | Meaning |
|---|---|---|---|
| `ids` | `<U36` | `(N,)` | chunk ids, aligned with rows |
| `vectors` | `float32` | `(N, D)` | embeddings (not normalised on disk) |
| `payloads` | `<U…` | `(N,)` | JSON string per point |
| `dim` | `int64` | `()` | `D`, for a clear mismatch error |

Payload JSON mirrors the previous schema:

```json
{
  "document_id": "uuid",
  "chunk_index": 12,
  "text": "…",
  "metadata": {"page_number": 3},
  "filename": "final.docx"
}
```

**In-memory state**: ordered `dict[id] -> vector` and `dict[id] -> payload`,
plus a lazily rebuilt normalised matrix and an `id -> row` index. Mutations
invalidate the matrix; reads build it once.

**Legacy migration**: when `vectors.npz` is missing and `vectors.json` exists,
load `{"points": [...]}`, write the binary archive, and leave the JSON file in
place. A corrupt archive is logged and treated as an empty store.

## SearchCacheEntry (process memory)

| Field | Type | Notes |
|---|---|---|
| `key` | tuple | `(chunks_version, normalised_query, top_k, search_type, document_ids, rerank, embedder_fingerprint)` |
| `results` | list[dict] | deep-copied on read/write |
| `created` | float | `time.monotonic()` for TTL |

Bounded by `SEARCH_CACHE_SIZE` (LRU eviction) and
`SEARCH_CACHE_TTL_SECONDS` (default 300s). `cache_stats()` exposes
`hits`, `misses`, `size`, `evictions`, `maxsize`.

## RateLimitBucket (process memory)

| Field | Type | Notes |
|---|---|---|
| `tokens` | float | starts at capacity |
| `updated` | float | `time.monotonic()` of last refill |
| `capacity` | float | requests allowed in a burst |
| `refill` | float | capacity / window seconds |

Map key: `(scope, client_ip)`, where `scope` ∈ {`search`, `chat`, `upload`} and
`client_ip` is the first `X-Forwarded-For` hop or the socket address. Buckets
idle for more than two windows are pruned when the map grows past 1,024 keys.

## Request ID

- Header: `X-Request-ID` on request/response.
- Accepted pattern: `[A-Za-z0-9._:-]{1,64}`; anything else is replaced by
  `uuid4().hex[:16]`.
- Stored in a `ContextVar`; attached to every `LogRecord` via a record factory,
  and included in the log format as `request_id=%(request_id)s`.

## Chunk metadata (DOCX)

`metadata.page_number` is now populated when the DOCX contains page breaks:

- Explicit `<w:br w:type="page"/>` and `<w:lastRenderedPageBreak/>` advance the
  page counter.
- Text before the first break is page 1; text after the last break keeps the
  incremented number.
- Tables are attached to the page current at the time the table is walked.
- If a DOCX has no break markers at all, the extractor returns a single page
  with `page_number = null`: Word pagination is layout-dependent, so no page is
  invented.
