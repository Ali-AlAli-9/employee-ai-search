# Implementation Plan: Retrieval & Operational Hardening

**Branch**: `009-retrieval-and-ops-hardening` | **Date**: 2026-11-19 |
**Spec**: [`spec.md`](./spec.md)

**Input**: [`spec.md`](./spec.md)

## Summary

Four independent hardening slices on the existing single-service FastAPI app:
(1) search each document before merging hits, reusing one query embedding;
(2) add read-only verification plus explicit-opt-in repair commands for the
document/chunk/vector triangle; (3) add an account-keyed login failure lock and
fix proxy IP selection; (4) correct two stale documentation lines. No new hosted
service, model download, Blueprint or paid provider is introduced.

## Technical Context

**Language/Version**: Python 3.11+, mypy-style hints; TypeScript 5 strict

**Primary Dependencies**: FastAPI, SQLite/psycopg 3, NumPy, local `.npz` or
optional Qdrant store, pytest; Next.js 14 frontend (untouched)

**Storage**: `documents`, `chunks`, `login_attempts` in SQLite or Postgres;
chunk vectors in the existing local file store or Qdrant

**Testing**: `py -3 -m pytest tests -q`; `npm.cmd test`, `npm.cmd run
type-check`, `npm.cmd run lint`

**Target Platform**: one Linux container on Render free tier (512 MB)

**Project Type**: web service + operator CLI scripts

**Performance Goals**: one embedding call per query; no per-document model load;
verification runs without starting the HTTP app

**Constraints**: offline default, no new dependency, no Blueprint, BYOK still
request-scoped and never stored, all user-visible errors still locally authored

**Scale/Scope**: tens of documents per deployment; one backend process

## Constitution Check

*Gates from `specs/001-employee-ai-search-platform/constitution.md`.*

| Principle | Status | Note |
|---|---|---|
| Test-Driven Development | PASS | Every slice gets failing tests first; full suites re-run at the end |
| Code Quality / type hints | PASS | New helpers are typed; existing lint/test gates remain |
| Security by default | PASS | Lockout counts unknown emails too, no raw detail in responses, proxy trust is explicit |
| Observability & reliability | PASS | Verification reports a failed check as failure, never a false green |
| Documentation as code | PASS | README, ARCHITECTURE and `.env.example` updated in the same change |
| Free-tier budget | PASS | No new service, model, or provider; local/SQLite paths tested offline |

No constitution violation, so no complexity-tracking exception is needed.

## Project Structure

```text
backend/app/
├── search.py          # per_document_search + one-shot query vector reuse
├── agents.py          # retriever uses per-document search
├── ratelimit.py       # trusted last-hop client IP
├── auth_api.py        # account lock check + failure accounting
├── config.py          # PER_DOCUMENT_TOP_K, TRUST_PROXY_HEADERS, lock settings
├── db.py              # login_attempts schema and helpers; chunk/admin helpers
├── consistency.py     # pure report + reconcile functions (new)
└── store.py           # all_points(), delete_points() (new)
backend/tests/
├── test_per_document_retrieval.py   (new)
├── test_consistency.py              (new)
├── test_account_lockout.py          (new)
└── test_ratelimit.py                (extended)
scripts/
├── verify_consistency.py            (new)
└── reconcile_documents.py           (new)
README.md · ARCHITECTURE.md · .env.example
specs/009-retrieval-and-ops-hardening/{spec,plan,tasks}.md
```

**Structure Decision**: keep the existing flat `backend/app` layout; operator
commands live beside the existing `scripts/seed.py` and `scripts/evaluate.py`,
so no new package is added.

## Technical Approach

### 1. Per-document retrieval

`_hybrid_search_uncached()` gains an optional precomputed `query_vector`. A new
cached `per_document_search()` resolves the target document ids from
`db.list_documents(status="completed")` (or the caller's explicit subset),
encodes the query once, calls the existing lexical/vector scorer once per
document with `document_ids=[doc_id]`, then merges by max score, deduplicates by
chunk id and truncates to `top_k`. `agents.retrieve()` calls it for each
sub-query; the `/search` endpoint keeps the existing global search so operators
can still compare the two.

### 2. Consistency tooling

`app/consistency.py` owns the report logic and is importable by tests. Both
store adapters gain `all_points()` and `delete_points()`. The checker compares
`documents.chunks_count` to real `chunks` rows, checks chunk→document
references, chunk→vector and vector→chunk presence, and flags `processing`
rows older than `--stale-minutes`. `reconcile()` is a no-op unless `apply=True`;
`--purge-orphans` and `--stale-minutes` are independent explicit switches. Stale
rows get a friendly fixed status string, never an exception message.

### 3. Account protection

`login_attempts.email` is lower-cased and trimmed by `db.normalise_login_key`.
The lock is checked before `identity.login()`; failures (including unknown
emails) increment the counter, success clears it. A lock returns `429` with
`Retry-After`. Rate-limit IP selection switches to the last hop when
`TRUST_PROXY_HEADERS=1` (default true for the hosted deployment) and otherwise
uses the socket peer.

### 4. Documentation

The README test count becomes 26; the architecture write path becomes
"any signed-in account"; new variables and both operator commands are added to
the README and `.env.example`.

## Testing Strategy

| Test | Proves |
|---|---|
| `test_per_document_search_calls_each_document_once` | FR-001, FR-002 |
| `test_per_document_search_honours_explicit_document_ids` | FR-001, edge |
| `test_retriever_uses_per_document_search` | FR-003 |
| `test_consistency_report_names_all_injections` | FR-009 |
| `test_reconcile_dry_run_changes_nothing` / `test_reconcile_apply_repairs` | FR-010 |
| `test_lockout_counts_all_emails_and_ignores_ip_rotation` | FR-005–FR-007 |
| `test_successful_login_clears_failures` | FR-006 |
| `test_client_ip_uses_trusted_last_hop` | FR-008 |
| README/ARCHITECTURE grep assertions in review | FR-012 |

## Rollout

1. Write the four spec-kit documents.
2. Write failing tests for each slice, run them, confirm failure.
3. Implement in the order P1 → P2 → P3 → P4, re-running the focused tests after
   each slice.
4. Run the full backend and frontend gates.
5. Amend the single root commit and force-push to `origin/main`.
6. The operator, not the agent, runs the new commands against the live database
   after the Render rebuild.
