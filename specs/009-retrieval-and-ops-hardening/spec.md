# Feature Specification: Retrieval & Operational Hardening

**Feature Branch**: `009-retrieval-and-ops-hardening`

**Created**: 2026-11-19

**Status**: Draft

**Input**: User request, following the comparison with `document-assistant-main`:
apply per-document retrieval, mature data-consistency tooling, stronger
account-level protection, and remove the two documentation drifts (frontend test
count and the "admin-only upload" line in `ARCHITECTURE.md`).

## User Scenarios & Testing

### User Story 1 - Every indexed document contributes to retrieval (Priority: P1)

A reader asks a question that spans several uploaded documents. Today one
dominant document can occupy the global top-K and push a smaller but relevant
document out of the evidence set. The system must search each candidate document
separately, then merge and re-rank the hits so each document gets a fair chance.

**Why this priority**: it changes answer quality directly and is the main
capability the comparison identified as missing. It stays fully offline and free.

**Independent Test**: with two completed documents and a monkeypatched retrieval
backend that returns one hit per document, a single query must produce hits from
both documents, sorted by score, with no duplicate chunk ids.

**Acceptance Scenarios**:

1. **Given** two completed documents with distinct content, **When** a query is
   searched with `per_document_top_k=1`, **Then** the retriever calls the
   underlying search once per document and merges both hits.
2. **Given** the same chunk is returned by two sub-queries or documents,
   **When** results are merged, **Then** only the highest-scoring copy survives.
3. **Given** `document_ids` are supplied by the caller, **When** per-document
   retrieval runs, **Then** only those documents are searched.
4. **Given** the configured embedding backend is a paid/API backend, **When** a
   per-document query runs, **Then** the query vector is computed once, not once
   per document.

---

### User Story 2 - Operator can verify and repair data consistency (Priority: P2)

An operator suspects a document row, its chunks and the vector store disagree
after an interrupted upload or a crash. The operator needs a read-only command
that reports the disagreement and a separate repair command that is inert unless
`--apply` is passed.

**Why this priority**: silent bad answers are worse than a failed upload. The
other project has `verify_consistency` and `reconcile_documents`; this project
currently has neither.

**Independent Test**: create a completed document with a stale `chunks_count`,
an orphan chunk and an orphan vector, then run the checker and assert all three
are named in the report; run the repair in dry-run mode and assert nothing
changed, then with `--apply` and assert only the declared repairs happened.

**Acceptance Scenarios**:

1. **Given** a completed document whose `chunks_count` differs from the real
   chunk rows, **When** verification runs, **Then** the document is reported as
   a count mismatch and the command exits non-zero.
2. **Given** a vector whose id is absent from the chunk table, **When**
   verification runs, **Then** it is reported as an orphan vector.
3. **Given** a document stuck in `processing` for longer than the configured
   threshold, **When** reconciliation runs with `--apply`, **Then** it becomes
   `failed` with a generic, friendly status message and no raw exception text.
4. **Given** reconciliation is run without `--apply`, **When** it finishes,
   **Then** no row and no vector was modified.

---

### User Story 3 - Login is protected per account, not only per IP (Priority: P3)

An attacker rotates source addresses while guessing one known account's
password. The existing per-IP bucket resets on every rotation. The system must
also count failures keyed by the normalised email, lock that account temporarily,
and count failures for unknown emails so the lock cannot reveal which accounts
exist.

**Why this priority**: password guessing is the cheapest attack on a public
registration product. The comparison identified the missing account axis.

**Independent Test**: make five failed logins for one email from five different
`X-Forwarded-For` values; the fifth and later attempts must return `429` with a
`Retry-After` header, while a different email can still try.

**Acceptance Scenarios**:

1. **Given** `LOGIN_LOCK_MAX_FAILURES=5`, **When** the fifth wrong password is
   sent for one email, **Then** that attempt and every later attempt are refused
   with `429` regardless of source IP, while other emails can still try.
2. **Given** a locked email, **When** the wait expires, **Then** the counter
   resets and a correct password signs in.
3. **Given** a successful login, **When** it completes, **Then** the failure
   counter for that email is cleared.
4. **Given** two spellings of the same email (case/whitespace), **When** failures
   are recorded, **Then** they share one counter.
5. **Given** a request behind the Render proxy with
   `X-Forwarded-For: client, edge`, **When** rate limiting reads the client IP,
   **Then** it uses the last hop (`edge`) when proxy headers are trusted, so a
   caller cannot reset its bucket by editing the first hop.

---

### User Story 4 - Documentation tells the truth (Priority: P4)

The README says the frontend has 19 tests (it has 26) and `ARCHITECTURE.md`
claims uploads are admin-only (any registered user may upload). Both must be
corrected, and the new operator commands and protection knobs must be documented
in English.

**Why this priority**: cheap to fix, and stale docs cause wrong operational
decisions.

**Independent Test**: grep both documents for the old strings and confirm the
new commands and defaults are present.

**Acceptance Scenarios**:

1. **Given** the current frontend suite, **When** the README test section is
   read, **Then** it states 26 tests.
2. **Given** the implemented access rules, **When** `ARCHITECTURE.md` is read,
   **Then** the write path says any signed-in account may upload and only admins
   may delete or replace another user's document.

---

### Edge Cases

- An empty document list must not cause per-document retrieval to call the
  embedder or the vector store at all.
- A per-document search that returns section-expanded chunks must not duplicate
  siblings already returned for another document.
- The consistency checker must not open a Postgres pool when configured for
  SQLite, and must report an unreadable vector store as an error instead of a
  clean bill of health.
- A lockout row for an unknown email must be swept after it goes stale so
  probing invented addresses cannot grow the table without bound.
- Turning proxy trust off must fall back to the socket peer, not to a spoofable
  header.

## Requirements

### Functional Requirements

- **FR-001**: Add `per_document_search()` to `backend/app/search.py`; it MUST
  search each selected document, merge by best score, deduplicate by chunk id,
  and honour the caller's `top_k`.
- **FR-002**: The query embedding MUST be computed once per query and reused for
  every document.
- **FR-003**: `agents.retrieve()` MUST use per-document search for sub-queries,
  keeping the existing text deduplication and trace fields.
- **FR-004**: Add `PER_DOCUMENT_TOP_K` (default 5) to config, `.env.example` and
  the README variable table.
- **FR-005**: Add a `login_attempts` table with a case-folded email key, failure
  count, `locked_until` and `updated_at`, created by `db.init_db()` for both
  SQLite and Postgres.
- **FR-006**: `/api/v1/auth/login` MUST check the account lock before verifying
  credentials and MUST record every failure, including unknown emails.
- **FR-007**: A lock response MUST be `429` with a generic localised-by-frontend
  detail and a `Retry-After` header; no exception text or email may be echoed.
- **FR-008**: Rate-limit client IP selection MUST use the last trusted
  `X-Forwarded-For` hop when `TRUST_PROXY_HEADERS=1`, else the socket peer.
- **FR-009**: Add `scripts/verify_consistency.py` (read-only, exit 1 on any
  mismatch) and `scripts/reconcile_documents.py` (dry-run unless `--apply`).
- **FR-010**: The repair tool MUST be able to mark stale `processing` documents
  as `failed`, remove orphan chunks and purge orphan vectors, each only when
  explicitly requested.
- **FR-011**: Add read/write helpers to the vector store abstraction for
  enumerating points and deleting explicit point ids, implemented for both the
  local file store and Qdrant.
- **FR-012**: Update `README.md` (26 frontend tests, new variables and commands),
  `ARCHITECTURE.md` (upload by any signed-in account), and `.env.example`.

### Key Entities

- **LoginAttempt**: normalised email, failures, `locked_until`, `updated_at`.
- **ConsistencyReport**: lists of count mismatches, orphan chunks, orphan
  vectors, missing vectors and stale processing documents.
- **PerDocumentHit**: the existing chunk hit shape, unchanged for callers.

## Success Criteria

- **SC-001**: Backend suite stays green with at least 12 new focused tests;
  frontend tests, type-check and lint stay green.
- **SC-002**: Every completed document gets at least one retrieval attempt when
  the query has evidence in it, verified by a deterministic unit test.
- **SC-003**: Five wrong passwords from five different IPs lock only that email.
- **SC-004**: The consistency checker reports all four injected inconsistencies
  and exits non-zero; dry-run repair changes nothing.
- **SC-005**: No raw exception, email or stored vector text appears in a user
  facing message or in the new commands' human output.

## Assumptions

- The single-instance free deployment remains the target; no Redis or external
  queue is introduced.
- Render terminates TLS and appends the real client address as the last
  `X-Forwarded-For` hop; operators exposing the app directly set
  `TRUST_PROXY_HEADERS=0`.
- Demo sessions are rate-limited by IP only; account lockout applies to the
  explicit email/password route.
- `README.md` and code comments stay in English; chat with the operator stays
  in Arabic.
