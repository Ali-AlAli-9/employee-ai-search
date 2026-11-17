# Implementation Plan: Performance & Safety

**Branch**: `002-performance-and-safety` | **Date**: 2026-11-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-performance-and-safety/spec.md`

## Summary

Replace the JSON vector store with an `.npz` store that keeps a cached,
L2-normalised matrix and answers a search with one `matrix @ query` operation;
detect duplicate uploads with a `sha256` column and offer `replace=true`; split
DOCX text at page breaks so chunks carry page numbers; memoise
`hybrid_search` with a corpus-versioned LRU/TTL cache; and add a per-IP token
bucket plus `X-Request-ID` propagation. All changes stay inside the existing
FastAPI + Next.js services and require no paid infrastructure.

## Technical Context

**Language/Version**: Python 3.11+ (FastAPI, Pydantic v2), TypeScript 5 with
Next.js 14 App Router.

**Primary Dependencies**: `numpy` (already installed for embeddings), FastAPI,
`python-docx`, `pypdf`, Next.js 14. No new runtime dependencies.

**Storage**: SQLite (`data/app.db`) + local vector file (`data/vectors.npz`),
WAL mode; optional Qdrant adapter unchanged.

**Testing**: `pytest` + FastAPI `TestClient`; `tsc --noEmit` for the frontend.

**Target Platform**: Render free web service (Linux container, 0.1 CPU,
512MB RAM, ephemeral disk) and local Windows/macOS/Linux dev.

**Project Type**: Web application — `backend/` (FastAPI) and `frontend/`
(Next.js).

**Performance Goals**: Store load < 1s for 5,000 chunks; one vectorised
similarity computation per search; cached repeat search < 5ms excluding
database bookkeeping.

**Constraints**: Zero new services/dependencies; in-memory caches ≤ a few MB;
answers must remain honest (abstention unchanged); no breaking API changes
(only an additive query parameter and a new `409` response).

**Scale/Scope**: One process, one index, ≤ 50MB files, ≤ 6,000 chunks per
document, a handful of concurrent demo users.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Notes |
|---|---|---|
| TDD (tests first, fail before implementation) | PASS | Every story has tests written before code (tasks T1/T2). |
| Clean architecture (API → services → storage) | PASS | Store stays behind `get_store()`; cache stays inside `search.py`; limiter is its own module. |
| Type hints / lint | PASS | New modules fully typed; no new lint disables except documented `# type: ignore` for optional imports. |
| Observability (request_id, structured logs) | PASS | FR-011 adds `request_id` to every application log record and an access log line. |
| Performance budgets | PASS | SC-001/SC-002; measured locally before merge. |
| Security/RBAC | PASS | Deleting remains admin-only; uploading requires any signed-in role; the limiter adds DoS protection; no key ever reaches the browser. |
| Zero-cost defaults | PASS | numpy/SQLite only; in-memory limiter/cache; optional Qdrant path untouched. |
| Backward compatibility | PASS | Legacy `vectors.json` auto-migrates; API adds `replace`/`409` only. |

No violations; no complexity exceptions required.

## Project Structure

### Documentation (this feature)

```text
specs/002-performance-and-safety/
├── spec.md
├── plan.md
├── data-model.md
├── tasks.md
└── contracts/openapi.delta.yaml
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api.py            # upload dedupe + replace, delete helper, limiter deps
│   ├── config.py         # new settings (hash column is migration-only)
│   ├── db.py             # content_hash column/index, lookup, migration
│   ├── ingestion.py      # DOCX page-aware extraction
│   ├── main.py           # request-id middleware + log factory, limiter wiring
│   ├── ratelimit.py      # NEW token bucket + FastAPI dependency
│   ├── search.py         # query cache + cache_stats/clear_cache
│   └── store.py          # NEW binary LocalVectorStore + migration
└── tests/
    ├── test_store.py     # round-trip, migration, vectorised ranking
    ├── test_dedupe.py    # 409 / replace / failed re-upload
    ├── test_docx_pages.py# page breaks + chunk metadata
    ├── test_cache.py     # hit/miss/invalidation/copy isolation
    ├── test_ratelimit.py # bucket maths + HTTP 429
    └── test_request_id.py# header echo/generate + log record
frontend/
├── app/api/v1/[...path]/route.ts  # forward X-Forwarded-For and X-Request-ID
├── lib/api.ts                     # replace option, duplicate error type
└── components/DocumentPanel.tsx   # "replace existing" action
```

**Structure Decision**: Keep the delivered flat layout (`backend/app`,
`frontend/{app,components,lib}`). The feature does not justify new packages;
only `ratelimit.py` is a new module.

## Phase 0 — Research (decisions)

1. **Binary format**: `numpy.savez` with `ids` (unicode array), `vectors`
   (float32 `N×D`), `payloads` (unicode array of JSON strings) and `dim`.
   `allow_pickle=False` keeps loading safe. Atomic write goes to
   `vectors.npz.tmp` then `os.replace`.
2. **Search**: normalise rows once into `self._matrix`; a search is
   `scores = self._matrix @ (q / ||q||)`. `argpartition` selects top-k, then a
   small sort. Document filters are applied with a boolean mask from payloads.
3. **Migration**: `settings.vectors_path` returns `vectors.npz`;
   `settings.legacy_vectors_path` returns `vectors.json`. The store loads the
   legacy file when the binary is missing, saves the binary, and leaves the
   JSON file in place (so a rollback still works).
4. **Dedupe**: hash after the size/type checks, before creating a row. A
   partial unique index (`WHERE content_hash IS NOT NULL`) prevents concurrent
   duplicates; `IntegrityError` maps to `409`.
5. **Cache**: wrapper around the existing `hybrid_search` body. Key includes
   `db.chunks_version()` (count + newest `created_at`), so insert/delete
   invalidates. `copy.deepcopy` on store and load. Bounded `OrderedDict` LRU +
   monotonic TTL.
6. **Rate limit**: token bucket with capacity = per-minute budget and refill =
   capacity/60s. One bucket per (scope, client IP); periodic pruning when the
   map is large. FastAPI dependency so endpoint signatures stay readable; auth
   dependencies run first so unauthorised calls do not consume quota.
7. **Request id**: contextvar + `logging.setLogRecordFactory` so every record
   carries `request_id` regardless of which handler emits it (pytest, uvicorn,
   root). Middleware validates the incoming header (`[A-Za-z0-9._:-]{1,64}`),
   generates `uuid4().hex[:16]` otherwise, sets the response header and logs
   `method path status duration_ms` at the end.

## Phase 1 — Design

- `data-model.md` documents the `content_hash` column/index/migration and the
  `.npz` schema.
- `contracts/openapi.delta.yaml` documents the additive `replace` parameter and
  the `409` response.
- No changes to the retrieval algorithm, chunking, or agent team.

## Phase 2 — Tasks

See [tasks.md](./tasks.md). Order: store → dedupe → DOCX → cache → rate limit /
request id → docs/validation.

## Complexity Tracking

No constitution violations.
