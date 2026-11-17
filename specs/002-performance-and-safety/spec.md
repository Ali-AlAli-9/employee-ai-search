# Feature Specification: Performance & Safety

**Feature Branch**: `002-performance-and-safety`

**Created**: 2026-11-15

**Status**: Draft

**Input**: User description: "Improve the Employee AI Search Platform: (1) faster vector store, (2) duplicate-upload detection, (5) DOCX page numbers + query cache, (6) rate limiting + request tracing — implemented with the spec-kit workflow."

## Context

The platform runs on the Render free tier: one 0.1 CPU worker, 512MB RAM, an
ephemeral disk. Three costs dominate the current behaviour:

1. Every upload rewrites the whole `vectors.json` file and every search walks
   every point in a Python loop, so retrieval and ingest get slower with each
   document.
2. Re-uploading the same file after a redeploy silently creates a second copy,
   which duplicates citations and doubles storage.
3. One anonymous visitor can hammer `/chat` (expensive) or `/documents/upload`
   (slow), and the logs cannot connect a line to a request.

This feature removes those costs without adding paid infrastructure, changing
the API contract in a breaking way, or weakening the honest-abstention
behaviour of the RAG pipeline.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Search stays fast as the corpus grows (Priority: P1)

An employee asks a question while the knowledge base holds several thousand
chunks. Retrieval must complete quickly on the free instance, and the service
must boot without spending tens of seconds parsing a text file of vectors.

**Why this priority**: Retrieval latency is the product. On a 0.1 CPU worker a
Python loop over every embedding is the largest controllable cost.

**Independent Test**: Build a store with 5,000 deterministic vectors, persist
it, reload it in a fresh instance, and assert top-1/top-5 results (and
document filters) match a brute-force cosine reference. Verify a legacy
`vectors.json` file is migrated on first load.

**Acceptance Scenarios**:

1. **Given** a store file written by the new binary format, **When** the app
   restarts, **Then** every point (id, vector, payload) is restored exactly.
2. **Given** an existing deployment with `data/vectors.json`, **When** the new
   version starts, **Then** the points are migrated to `data/vectors.npz` and
   searches return the same results as before.
3. **Given** a search restricted to one document, **When** scores are computed,
   **Then** only that document's chunks are returned, ordered by descending
   similarity.
4. **Given** a document is deleted, **When** the next search runs, **Then** none
   of its chunks are returned and the store count drops accordingly.

---

### User Story 2 - Uploading the same file twice is explicit (Priority: P1)

An admin re-uploads `final.docx` after a redeploy. Instead of silently creating
a duplicate, the API tells them the file already exists and returns the existing
document id; passing `replace=true` replaces the old copy in one step.

**Why this priority**: Duplicates corrupt result quality (two identical
citations) and waste the small disk; re-uploading is the normal workflow here
because the free tier loses data on redeploy.

**Independent Test**: Upload a file twice and assert `409` with the existing
`document_id`; upload the same bytes with `replace=true` and assert `202`, a new
id, the old id gone, and only one document with that content hash.

**Acceptance Scenarios**:

1. **Given** a completed document, **When** the same bytes are uploaded again,
   **Then** the API returns `409` naming the existing document and creates
   nothing.
2. **Given** the same situation with `replace=true`, **When** the upload is
   accepted, **Then** the old document, its chunks and its vectors are removed
   before the new document is indexed.
3. **Given** a document whose ingestion failed, **When** the same bytes are
   uploaded again, **Then** the upload is accepted (a failure is not a
   duplicate).
4. **Given** two different files with different bytes, **When** both are
   uploaded, **Then** both are accepted.

---

### User Story 3 - DOCX citations show real page numbers (Priority: P2)

An employee asks about a paragraph in a Word report and the source card shows
"page 12" instead of no page at all.

**Why this priority**: Citations without a page cannot be verified by a reader;
the PDF path already supplies them. It is a small, isolated change.

**Independent Test**: Build a DOCX in memory with a page break and a rendered
page break, extract it, and assert the returned pages are numbered and that the
chunks derived from them carry `metadata.page_number` accordingly.

**Acceptance Scenarios**:

1. **Given** a DOCX with an explicit page break (`<w:br w:type="page"/>`),
   **When** it is ingested, **Then** chunks after the break carry the next page
   number.
2. **Given** a DOCX with Word's `<w:lastRenderedPageBreak/>` markers, **When**
   it is ingested, **Then** those markers also advance the page counter.
3. **Given** a DOCX with no page information, **When** it is ingested, **Then**
   `page_number` stays `null` (no invented pages).

---

### User Story 4 - Repeated questions are answered from cache (Priority: P2)

Several employees (or the same employee refreshing) ask the same question. The
second and later identical searches must not recompute embeddings or rerank
scores, while any change to the corpus must invalidate the cached answer.

**Why this priority**: It is the cheapest latency win for demos and repeated
questions, and it is safe only when invalidated correctly.

**Independent Test**: Call the same search twice and assert the second call is
a cache hit with identical results; upload a document, call again, and assert a
cache miss and fresh results. Mutating the returned list must not poison the
cache.

**Acceptance Scenarios**:

1. **Given** an unchanged corpus, **When** the same query is run twice, **Then**
   the second call is served from cache (`cache_stats()["hits"]` increases) and
   returns equal results.
2. **Given** a corpus change (upload/delete), **When** the same query is run,
   **Then** the cache is bypassed for that version and new results are used.
3. **Given** different `top_k`, `search_type`, `document_ids` or `rerank`
   values, **Then** the cache treats them as different entries.

---

### User Story 5 - Abuse is limited and every request is traceable (Priority: P3)

An operator can find all log lines for one request in Render's log viewer, and
a burst of automated calls is rejected with `429` instead of consuming the
worker.

**Why this priority**: It is operational hardening; the product works without
it, but a public demo needs both.

**Independent Test**: Send `X-Request-ID: trace-123` and assert the response
echoes it and the log record carries it; send requests beyond the configured
limit and assert `429` with a `Retry-After` header.

**Acceptance Scenarios**:

1. **Given** a request without `X-Request-ID`, **When** it is handled, **Then**
   a fresh id is generated, returned in the response header, and attached to
   every log line produced while handling it.
2. **Given** a request with `X-Request-ID`, **When** it is handled, **Then** the
   same id is echoed.
3. **Given** more requests than the per-IP budget, **When** another request
   arrives, **Then** it fails with `429` and `Retry-After` seconds.
4. **Given** the limiter is disabled by configuration, **When** requests burst,
   **Then** none are rejected.

### Edge Cases

- A vector file written by an older version must not crash the service: a
  corrupt or unreadable file is treated as an empty store and logged.
- Changing `EMBEDDING_DIMENSION` while a store exists must fail ingestion with a
  clear message rather than mixing dimensions silently.
- A duplicate upload of a file that is still `processing` is still a duplicate
  (its hash is already recorded).
- Deleting or replacing a document while its ingestion runs must not resurrect
  its chunks or vectors; the worker detects the missing row and cleans up.
- The rate limiter must not grow without bound: idle per-IP buckets are pruned.
- Request ids supplied by clients are sanitised (length/characters) before being
  logged or echoed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The local vector store MUST persist vectors in a binary format
  (`.npz`) with atomic replacement, while keeping the public interface
  `upsert`, `delete_document`, `count`, `search`.
- **FR-002**: On startup, if the binary file is absent and a legacy
  `vectors.json` exists, the store MUST migrate it automatically and keep the
  original file untouched.
- **FR-003**: Search MUST compute cosine similarity with a single vectorised
  matrix operation and return the top-k results ordered by descending score,
  honouring the `document_ids` filter.
- **FR-004**: The documents table MUST record a `sha256` content hash with an
  index; existing databases MUST be migrated in place without data loss.
- **FR-005**: `POST /api/v1/documents/upload` MUST return `409` with the
  existing document id when the same bytes are already indexed, unless
  `replace=true` is supplied.
- **FR-006**: With `replace=true`, the previous document (row, chunks, vectors)
  MUST be removed before the new document is created; only the original uploader
  or an administrator may replace it (`403` otherwise).
- **FR-007**: DOCX extraction MUST split text at explicit and rendered page
  breaks and attach `page_number` to each produced chunk.
- **FR-008**: `hybrid_search` MUST cache results in memory keyed by the corpus
  version, normalised query, `top_k`, `search_type`, `document_ids`, `rerank`
  and embedder identity, with a bounded size and a TTL.
- **FR-009**: Cached results MUST be returned as copies so callers cannot
  mutate the cache; `cache_stats()` MUST expose hits, misses, size and
  evictions.
- **FR-010**: `/chat`, `/search` and `/documents/upload` MUST enforce a per-IP
  token-bucket rate limit (configurable per endpoint) and return `429` with
  `Retry-After` when exhausted.
- **FR-011**: The API MUST echo or generate `X-Request-ID`, include it in every
  response, and add `request_id` to application log records.
- **FR-012**: The web proxy MUST forward the original client address
  (`X-Forwarded-For`) so per-IP limits work behind the Next.js service.
- **FR-013**: Existing tests and evaluation results MUST keep passing; no
  change may reduce retrieval quality (hit@k, citation accuracy) on
  `eval/thesis-questions.json`.
- **FR-014**: If a document is deleted or replaced while its ingestion task is
  still running, the task MUST NOT resurrect chunks or vectors for that
  document id, and a failed ingestion MUST leave no partial vectors behind.

### Key Entities

- **Document**: adds `content_hash` (hex sha256, unique when present) to the
  existing document record.
- **VectorPoint**: `id`, float32 `vector`, JSON `payload` (`document_id`,
  `chunk_index`, `text`, `metadata`, `filename`); persisted in `vectors.npz`.
- **SearchCacheEntry**: key tuple, cached result list, insertion time; kept in
  memory only.
- **RateLimitBucket**: client key, token count, last refill time; kept in
  memory only.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Loading a 5,000 × 384 store from disk takes < 1s on the free
  instance (measured locally), versus tens of seconds for the JSON format.
- **SC-002**: A single search over 5,000 chunks performs one matrix multiply
  instead of 5,000 Python-level dot products (verified by inspection plus a
  reference-equivalence test).
- **SC-003**: A duplicate upload is rejected in a single request cycle with the
  existing id; `replace=true` leaves exactly one document per content hash.
- **SC-004**: DOCX chunks carry page numbers whenever the document contains page
  breaks; PDF chunk behaviour is unchanged.
- **SC-005**: A repeated identical search costs a dictionary lookup plus a
  deep copy, and is invalidated by any upload or delete.
- **SC-006**: The 21st chat request from one IP in a minute (default) returns
  `429`; the response includes `Retry-After`.
- **SC-007**: 100% of application log lines emitted while handling a request
  contain that request's id.
- **SC-008**: `pytest` (54 tests) and `tsc --noEmit` pass; evaluation scores are
  not lower than the recorded baselines.

## Assumptions

- One embedding backend/dimension is used per deployment; changing it requires
  a clean data directory.
- The service is a single process (Render free instance), so in-memory caches
  and limiters are authoritative; no cross-worker coordination is needed.
- `X-Forwarded-For` from Render's edge is trustworthy; the Next.js proxy
  forwards it unchanged.

