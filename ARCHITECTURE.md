# Architecture

> Companion to the [README](./README.md). This document explains **why** the system is built
> the way it is, what it deliberately does not do, and where it breaks first.

---

## 1. Goals and non-goals

**Goals**

1. Answer questions over an organisation's own documents with *traceable* citations.
2. Ship a complete, demo-able product on free infrastructure (Render free tier, no paid APIs).
3. Keep every external dependency swappable (embeddings, vector store, LLM) behind a small interface.
4. Be readable as a portfolio artifact: clear module boundaries, typed contracts, tests.

**Non-goals**

- Multi-tenant isolation, SSO, document-level ACLs (the RBAC model is role-based, not per-document).
- Horizontal scale. The design assumes **one** backend instance.
- Perfect OCR. Scanned PDFs without a text layer are not supported.
- Durable ingestion. There is no external queue and no retry; see §9.

---

## 2. Component map

| Module | Responsibility | Key decision |
| --- | --- | --- |
| `app/main.py` | App wiring, lifespan, CORS, error handler | Schema created at import *and* in lifespan, so test clients that skip lifespan still work |
| `app/api.py` | HTTP surface, SSE framing, trace persistence | Sync endpoints (CPU/IO bound) run in FastAPI's threadpool; no async DB driver needed |
| `app/security.py` | API key, session cookie *or* Supabase access token → `Principal`, `require_role(min)`, CSRF | One dependency for every credential; API keys keep their role name as principal id so old history still resolves |
| `app/identity/` | Provider facade: `local.py` (scrypt + sessions) and `supabase.py` (GoTrue + JWT), plus bootstrap and the `profiles` read model | Routes never branch on the provider; `AUTH_PROVIDER` is resolved once at import |
| `app/auth_api.py` | `/auth/demo`, `register`, `login`, `logout`, `me` + user management | Guests are real `viewer` rows, so every downstream route is unchanged; guards live in one helper |
| `app/ingestion.py` | Extract → chunk → embed → index | Character-window chunking with whitespace-aware boundaries; TOC-only chunks dropped; visual-order Arabic PDFs repaired; page metadata preserved for citations |
| `app/embeddings.py` | `HashingEmbedder`, `SentenceTransformerEmbedder`, `HFInferenceEmbedder`, `GeminiEmbedder` | Hashing is deterministic and offline, so the hosted API never downloads a model; optional API/local backends are swappable behind `embed`/`embed_one` |
| `app/store.py` | `LocalVectorStore`, `QdrantStore` | Same `upsert/search/delete_document/count/all_points/delete_points` contract; file store rewrites atomically via temp file |
| `app/search.py` | Per-document retrieval, hybrid scoring + coverage rerank + section anchoring | Weighted sum of normalised signals, not raw cosine; one embedding per query |
| `app/consistency.py` | Read-only index report + opt-in repair plan | Never writes without `apply=True`; an unreadable vector store is a failed check |
| `app/ratelimit.py` | Per-IP token buckets, trusted last-hop client address | In-process only; `TRUST_PROXY_HEADERS=false` falls back to the socket peer |
| `app/structure.py` | Numbered-heading parser and section windows | Text-only: no document model, no page assumptions, works for DOCX and PDF text |
| `app/agents.py` | Researcher → Retriever → Synthesizer, LLM client, orchestrator | One `complete_json` call per stage, both optional |
| `app/byok.py` | Visitor-supplied LLM credential, request-scoped | `ContextVar` + allow-listed base URL; nothing persisted or logged |
| `app/db.py` | Portable schema and queries, SQLite **or** Postgres | One connection wrapper: `?`→`%s`, `ON CONFLICT` upserts, per-dialect schema introspection; psycopg imported lazily |

### Frontend client (Next.js 14)

`frontend/components/ChatInterface.tsx` is the only stateful client controller: it owns health,
identity, BYOK flags and the streaming chat pipeline. It renders `AppShell` (responsive sidebar,
mobile drawer, top bar) and five presentational views under `components/views/` — Chat, Library,
Users, Settings and Auth. The views receive real data and callbacks; they never instantiate mock
users, documents or chat replies. The visual tokens (blue primary, emerald accent, neutral
surfaces, Inter / Noto Naskh Arabic) were adapted from a local design prototype that was used
strictly as a visual reference. `data-theme` and the `eais-lang` key remain the single sources of
truth for theme and language; `lib/format.ts` supplies locale-neutral file-size and relative-time
labels. The Next proxy (`app/api/v1/[...path]/route.ts`) is unchanged and keeps forwarding only
the caller's own BYOK headers.

---

## 3. Data flow

### 3.1 Ingestion (write path)

```
upload (multipart, any signed-in account)
   └─▶ validate extension + size (≤ 50 MB)
       └─▶ INSERT documents(status='pending'), return 202
           └─▶ BackgroundTasks: ingest_document()
                 ├─ status='processing'
                 ├─ extract_pages()   PDF (pypdf, per page + visual-order repair) | DOCX (python-docx) | TXT/MD (encoding cascade)
                 ├─ chunk_text()      ~256 tokens, 40 overlap, cuts on whitespace, drops dotted-leader TOC chunks
                 ├─ embed()           batch → float32 vectors
                 ├─ store.upsert()    vector + payload {document_id, chunk_index, text, page, filename}
                 ├─ INSERT chunks     text is duplicated in SQLite for keyword search and display
                 └─ status='completed' (chunks_count, completed_at) | status='failed' (error_message)
```

**Why duplicate the text?** Keyword scoring and citation rendering need the chunk text without
deserialising the whole vector file. At demo scale the duplication is far cheaper than a join
against an external store.

**Atomicity:** vectors are written *before* chunk rows, then the document is marked complete.
A crash between the two leaves orphan vectors — harmless for search (the join in `get_chunks`
drops ids with no row) but they do consume space. The opposite ordering would leave chunks that
can never be retrieved.

### 3.2 Query (read path)

```
POST /chat {message, history, language}
   ├─ Researcher.plan()      LLM JSON or regex splitter → {sub_queries[], strategy}
   ├─ Retriever.retrieve()   for each sub-query: hybrid_search(); merge by max score; top-k
   ├─ Synthesizer.synthesize() LLM JSON or extractive fallback → {answer, citations[], confidence}
   └─ SSE: token* → citation* → done   (+ persist query row and trace)
```

`POST /search` is the same retrieval stage without the agents — useful for debugging ranking
and for the "show me the raw hits" story in interviews.

---

## 4. Ranking

For a query `q` and chunk `c`:

```
vector(c)  = cosine(q, c) rescaled to [0,1]              # (cos + 1) / 2
bm25(c)    = Okapi BM25 over content terms, / ceiling    # k1=1.2, b=0.75
coverage(c)= Σ idf(t) for t ∈ q∩c  /  Σ idf(t) for t ∈ q # IDF-weighted, in [0,1]
base(c)    = α · vector(c) + (1-α) · bm25(c)             # α = HYBRID_ALPHA
w          = HASHING_VECTOR_WEIGHT (0.0) with hashing; α with a trained embedder
score(c)   = (1-β) · base(c) + β · coverage(c)           # β = RERANK_COVERAGE_WEIGHT (0.5)
```

Notes and honest limitations:

- Content terms are produced by an AR/EN stopword list, a light Arabic stemmer
  (`الإطارات` → `اطار`, `كلمة المرور` → `كلم مرور`) and decimal-aware tokenisation
  (`0.32` stays one token). Without this, every question and every paragraph shared the
  words `the`/`من` and the ranking was effectively random.
- **Abstention gate:** with the hashing backend, a chunk needs `coverage ≥
  HASHING_MIN_COVERAGE` (0.35) to be a candidate at all. If no chunk clears it the search
  returns nothing and the chat answers "not found in the indexed documents" instead of
  quoting an unrelated paragraph.
- The rescaled cosine is **not** a calibrated probability; it is only used for ordering and for
  a rough confidence signal. Negative cosines are clamped to 0.
- `HASHING_VECTOR_WEIGHT` defaults to 0 because the hashing vector is a bag of the same
  content terms BM25 already scores — it adds noise, not semantics. A trained embedder earns
  the full `HYBRID_ALPHA` share.
- The rerank stage is a cheap feature blend, **not** a cross-encoder. A cross-encoder
  (`bge-reranker-base`) is the obvious upgrade; it was skipped to keep the free-tier image small.
- Hashing embeddings capture lexical similarity, not meaning. That is acceptable here:
  `HASHING_VECTOR_WEIGHT=0` keeps them out of the final score, BM25 leads retrieval, and
  the LLM reads the retrieved chunks and decides how to answer. The hosted deployment
  therefore uses `EMBEDDING_BACKEND=hashing` — instant, deterministic, offline, with no
  model download, no second service, no provider key, no token balance and no RPM/TPM
  quota. A previous two-service ONNX worker was retired: loading a quantised model even
  at batch 8 peaked around 330 MB RSS (and ~764 MB at batch 64), which killed Render's
  512 MB free container mid-upload. Removing it makes the deploy a single API service;
  Gemini and Hugging Face `hf-api` remain selectable as optional backends.
- Text is normalised before embedding and keyword scoring: Arabic diacritics and tatweel are
  stripped and alef/yaa/taa-marbuta variants are unified, so `بُعد` and `بعد` match. This is what
  makes the offline Arabic demo work at all.
- Retrieval asks every completed document for its own top-K slice (`PER_DOCUMENT_TOP_K`, default
  5) and then merges globally by best score. The query embedding is computed once per query, so
  API-backed embedders do not multiply their quota; a short relevant file cannot be crowded out
  by one long dominant document.
- Duplicate chunk texts (re-uploaded or overlapping documents) are collapsed by best score
  before synthesis, so citations never repeat the same passage.
- When the index holds both scripts, chunks in the requested answer language are **moved to the
  front** of the evidence set but not dropped: an English question over an Arabic report still
  needs the Arabic chapter that holds the fact.
- Corpus statistics (document frequency, average length) are cached in-process and invalidated
  by a `chunks_version()` fingerprint (`COUNT + MAX(created_at)`), so an upload is visible
  immediately without re-counting every chunk on every query.

### 4.1 Section anchoring

A question that repeats a numbered heading (`تنفيذ مرحلة التعرف على الوجه` → `3-5`) is a
near-exact lexical match for the heading line, but the answer lives in the paragraphs *under*
it. The heading often sits at the end of a chunk, right after a figure caption, so the naive
top-1 was the caption, not the section.

```
match_heading(q, chunk)  → heading whose title covers ≥75% of q and vice versa
window(text, number)     → (start, stop) lines: own heading / first different section
expand(anchor)           → next RETRIEVAL_SECTION_EXPAND chunks, same document
```

- Expansion happens **after** ranking and inherits the anchor's score (minus a tiny offset to
  keep reading order); it never fabricates a higher score. Siblings are inserted where the
  anchor ranked, and the anchor itself stays first.
- `section_window` cuts the previous section's tail (before the heading) and the next section's
  head (after the first heading with a different number), so a chunk boundary never leaks
  neighbouring prose.
- The synthesizer sees `section: {number, mode}` on the chunks. For `mode = "title"` it answers
  from the section body only and drops heading, caption and table lines. If no body line shares
  a term with the question, the section's opening prose is used — the exact title is itself the
  evidence. A breadth question (`كل الفصول`) expands too, but is marked `mode = "breadth"` and
  keeps the normal sentence ranking.
- Retrieval cost is bounded: headings are parsed only on the top 50 candidates, and expansion
  fetches at most three rows by `(document_id, chunk_index)`.

Measured behaviour on a real 126-chunk Arabic thesis with the offline backend — hit@5 0.667,
MRR 0.522, answer accuracy 0.667, abstention 0.750 — is documented with the full failure
taxonomy in [README → Evaluation](./README.md#evaluation-measured-not-claimed). The separate
section-title set scores hit@3 1.000 and answer accuracy 1.000, and the headline benchmark is
unchanged by the feature.

---

## 5. Agent contract

Defined in [`contracts/agent-interfaces.yaml`](./specs/001-employee-ai-search-platform/contracts/agent-interfaces.yaml).

| Stage | Input | Output | Deterministic fallback |
| --- | --- | --- | --- |
| Researcher | question + last 4 turns | `{sub_queries[≤5], search_strategy, confidence}` | regex split on `? ؟ , ، و and ;` |
| Retriever | plan + filters + top_k | `{chunks[], duration_ms}` | always deterministic |
| Synthesizer | question + ≤8 chunks + language | `{answer, citations[], confidence}` | globally ranked sentences by IDF coverage, one per chunk, `[n]` markers |

Both LLM stages are **fail-open**: malformed JSON, timeouts, HTTP errors, or a missing key all
fall through to the deterministic path. That is why the test suite can assert real answers with
`LLM_API_KEY` unset.

**Whose key is used?** `LLMClient` resolves the configuration at call time from
:mod:`app.byok`. `Orchestrator.run()` wraps the pipeline in `using_llm(config)`, which sets a
`ContextVar` and resets it in `finally`. A visitor's key therefore overrides the server key for
exactly one request, including the streaming path (the generator runs inside the same call).
Header validation — length, no whitespace/control characters, model charset, and an exact-match
base-URL allow-list — happens *before* any outbound request. `traces.data_json.llm_source`
records `"user"`, `"server"` or `"none"` (no provider called), and the same value is returned as
`llm_source` in the chat response so the UI can recognise a weak fallback. The credential itself
is never serialised anywhere.

The fallback is extractive on purpose: it prefers quoting a sentence that shares terms with the
question over inventing prose. When nothing matches, it says so in the user's language.

Confidence = mean of the top-3 chunk scores (heuristic mode), or the model's self-reported value
clamped to `[0,1]`. Treat it as a progress indicator, not a guarantee.

---

## 6. Storage

### Relational data (SQLite by default, Postgres when `DATABASE_URL` is set)

```
documents(id, filename, stored_filename, content_type, size_bytes, status,
          chunks_count, error_message, uploaded_by, created_at, updated_at,
          completed_at, content_hash)
chunks(id, document_id→documents, chunk_index, text, token_count, metadata_json, created_at)
queries(id, query_text, query_type, user_id, results_count, latency_ms, trace_id, created_at)
traces(id, query_id, data_json, created_at)
users(id, email UNIQUE, password_hash, role, display_name, is_active, is_guest,
      created_at, last_login_at)
sessions(id, user_id→users ON DELETE CASCADE, token_hash UNIQUE, csrf_hash,
         expires_at, created_at, user_agent)
login_attempts(email PRIMARY KEY, failures, locked_until, updated_at)
```

- **SQLite** (`DATA_DIR/app.db`): `PRAGMA journal_mode=WAL` + `foreign_keys=ON`; one short-lived
  connection per operation. **Postgres** (`DATABASE_URL`): a lazy `psycopg` 3 pool
  (`min_size=0`, `max_size=4`), so a sleeping free instance holds no idle sessions.
- One small `CompatConnection` wrapper keeps the SQL identical: `?` placeholders become `%s`,
  upserts use `ON CONFLICT`, and column existence is inspected through `information_schema` or
  `PRAGMA table_info`. `postgres://` is normalised to `postgresql://`.
- `users.email` is unique and stored lower-cased. Guests get `guest+<uuid>@guest.local` with the
  stored hash `"!"`, which can never verify a password.
- `sessions.token_hash` and `sessions.csrf_hash` are SHA-256 hex; the raw tokens exist only in the
  browser. Expired rows are deleted at the start of the next demo/register/login call.
- `login_attempts.email` is case-folded and trimmed, so `User@Example.com` and
  ` user@example.com ` share one counter. The row is deleted after a successful sign-in or when
  an expired lock is checked; stale rows are swept after 24 hours. No email is logged.
- Writes are serialised by SQLite itself; the module-level lock only guards schema creation.
- `UNIQUE(document_id, chunk_index)` makes re-ingestion idempotent per document.

### Vector store (`DATA_DIR/vectors.npz`)

`numpy.savez` archive (uncompressed, `float32`) with four arrays:

| Array | Shape | Meaning |
| --- | --- | --- |
| `ids` | `(N,)` | chunk ids, aligned with rows |
| `vectors` | `(N, D)` | embeddings (not normalised on disk) |
| `payloads` | `(N,)` | JSON string per point (`document_id`, `chunk_index`, `text`, `metadata`, `filename`) |
| `dim` | `()` | `D`, so a dimension mismatch fails with a clear message |

- Entirely in memory, rewritten atomically (`vectors.npz.tmp` + `replace`) after each upsert.
- The first search after a mutation builds a normalised `N×D` matrix once; every subsequent
  search is a single `matrix @ query` plus an `argpartition` top-k. No Python loop over points.
- A `document_ids` filter is a boolean mask over the payloads, so filtered search keeps the
  same vectorised path.
- **Legacy migration:** if `vectors.npz` is absent and `vectors.json` exists, the old points are
  loaded, the binary archive is written, and the JSON file is left untouched so a rollback works.
  A corrupt archive is logged and treated as an empty store instead of crashing boot.
- Vectors are dropped only when a document is deleted; there is no compaction step. Linear scan
  is fine to ~10⁵ chunks on one instance — beyond that, set `QDRANT_URL`.

### Qdrant (optional)

`QdrantStore` creates the collection if missing, maps `search` → `query_points` on newer clients
(falls back to the legacy `.search`), and filters by `document_id` with `MatchAny`. Payload shape
is identical to the local store, so the payload is the portable contract.

### Consistency tooling

`app/consistency.py` compares the three sources of truth — `documents.chunks_count`, real `chunks`
rows and vector-store points — without starting the HTTP app. `scripts/verify_consistency.py` is
read-only and exits `1` on any mismatch or unreadable store.
`scripts/reconcile_documents.py` prints a plan first and only writes with `--apply`; orphan purges
need the separate `--purge-orphans` flag. Stale `processing` rows become `failed` with a fixed,
friendly message so the operator can delete and re-upload them. Missing vectors are *reported*,
not fabricated. Run both with the same `DATA_DIR` / `DATABASE_URL` / `QDRANT_URL` as the API.

---

## 7. Security model

- **Authentication:** two credentials side by side. Browsers use an HttpOnly cookie — the local
  `eais_session` (an opaque 32-byte token whose SHA-256 is stored in `sessions`) or, in Supabase
  mode, `eais_access` + `eais_refresh`; scripts keep using `X-API-Key` exactly as before. All
  resolve to a `Principal(kind, id, role, email, is_guest)`.
- **Passwords:** in local mode `hashlib.scrypt` (n=2¹⁴, r=8, p=1) with a 16-byte salt. An unknown
  email still pays one dummy verification, and every failure returns the same generic `401`, so
  neither the message nor the timing discloses whether an account exists. In Supabase mode GoTrue
  owns the hashes and the platform never sees a password beyond the login request.
- **Sessions:** local sessions expire after `SESSION_TTL_HOURS`; Supabase access tokens last one
  hour and refresh transparently with rotation. Cookies are `HttpOnly`, `SameSite=Lax`, `Secure`
  in production. Only local session hashes are stored, so a database leak does not hand out live
  sessions. A deactivated user is rejected even with a cryptographically valid cookie.
- **CSRF:** double submit, never a GET. Cookie-authenticated POST/PUT/PATCH/DELETE need
  `X-CSRF-Token`: local mode compares it with the session's stored hash, Supabase mode requires
  header == readable `eais_csrf` cookie (stateless, not rotated on refresh). API keys are exempt
  because a key is not an ambient credential. The API client copies the value from the readable
  cookie; the proxy only forwards a caller-supplied header and never derives one itself —
  deriving it there would let any request that rides the cookie through the proxy pass the check.
- **Registration:** public by default — with `INVITE_CODE` unset anyone can create an account. Set a
  shared code to switch to invite-only (constant-time compare); the API advertises the mode as
  `checks.auth.invite_required` so the UI can ask for the code only when the deployment needs it. In
  Supabase mode the account is created with `email_confirm: true`, and when a code is configured it —
  not email ownership — is the trust boundary. Guests (`DEMO_LOGIN_ENABLED`) are `viewer` rows in
  local mode and anonymous GoTrue users in Supabase mode. The operator account is created or
  repaired from `ADMIN_EMAIL` / `ADMIN_PASSWORD` at every start; the password is never logged.
- **Authorisation:** `require_role("viewer" | "user" | "admin")` returns a `Principal`; any
  signed-in account may upload, search/chat/history/list are viewer+, and deleting documents or
  replacing another account's document is admin-only. In Supabase mode the role comes
  from `app_metadata` (not user-editable) and the `profiles` row is checked on **every** request,
  so a demotion or deactivation applies immediately rather than when the JWT expires.
- **Key exposure:** the browser only talks to the Next.js origin; the route handler forwards the
  cookie and no longer holds a backend key. Setting `NEXT_PUBLIC_API_URL` switches to direct
  browser → API calls, which needs an explicit `CORS_ORIGINS` list: `allow_credentials` is off
  when the list contains `*`.
- **Upload safety:** extension allow-list, 50 MB cap, ingestion failures surfaced as document
  state rather than 500s. No virus scanning, no sandboxing of parsers (pypdf/python-docx run
  in-process — a real deployment should parse out-of-process).
- **Abuse control:** per-IP token buckets on `/search`, `/chat`, `/documents/upload`, `/auth/*`
  and `/auth/users*` (`RATE_LIMIT_*_PER_MINUTE`), with `429` + `Retry-After`. The limiter is
  in-process, so it is authoritative only because the free instance is a single process. Auth
  runs before the limiter, so unauthorised calls do not consume quota. Behind a proxy the last
  `X-Forwarded-For` hop is the client (`TRUST_PROXY_HEADERS=true`); direct deployments set it to
  `false` to use the socket peer. Login additionally has an account-keyed failure lock
  (`LOGIN_LOCK_MAX_FAILURES=5`, `LOGIN_LOCK_MINUTES=15`). Unknown emails are counted too, so the
  lock cannot become an account-existence oracle, and provider outages are not counted.
- **Duplicate uploads:** a SHA-256 `content_hash` column with a partial unique index
  (`WHERE content_hash IS NOT NULL AND status != 'failed'`) rejects the same bytes with `409`;
  `?replace=true` deletes the previous document, chunks and vectors first.
- **Bring-your-own-key:** a visitor's credential arrives in `X-LLM-API-Key` (plus optional
  `X-LLM-Model` / `X-LLM-Base-URL`), is held in a request-scoped `ContextVar`, and is never
  persisted, logged, traced or echoed. The base URL must exactly match
  `LLM_ALLOWED_BASE_URLS` (OpenAI, OpenRouter, Groq), which closes the SSRF/key-exfiltration
  hole that an arbitrary base URL would open. `LLM_BYOK_ENABLED=false` rejects the headers with
  `403` and hides the UI. The browser keeps the key in `sessionStorage`, never `localStorage`.
  `REQUIRE_CHAT_BYOK=false` (default) preserves the free deterministic path; `true` applies the
  existing `402` contract to every keyless non-admin chat before the pipeline runs. The health
  probe publishes the flag as `checks.llm_api.require_chat_byok`, and the chat UI shows a localised,
  non-blocking BYOK hint only when a deterministic answer has low confidence or no citations.
- **Known gaps:** no MFA, no per-document ACLs, no audit trail (`queries.user_id` is the principal
  id, not a record of *who read what*), and guest profiles are not reaped automatically. Local
  mode still lacks password reset and the user-management UI (both exist in Supabase mode).

---

## 8. Observability

- `GET /api/v1/health` reports per-component status; `GET /health/ready` is the Render probe.
- **Request tracing:** middleware echoes a valid `X-Request-ID` (or generates one), returns it on
  every response, and a log-record factory stamps `request_id` on *every* log line emitted while
  handling the request. One access log per request carries method, path, status and duration.
- **Search cache:** repeat searches keyed by corpus version + normalised query + options are
  served from an in-memory LRU/TTL (`cache_stats()` / `clear_cache()`). Any upload or delete
  changes the corpus version and therefore invalidates stale entries.
- Each query stores a `traces` row: sub-queries, strategy, chunk count, per-stage latency,
  confidence, `llm_source` (`user` / `server` / `none`), and whether the LLM was enabled.
  `GET /chat/history` rehydrates answers and citations from these rows.
- `main.py` installs a catch-all exception handler that logs the stack and returns a generic 500
  (no internals leaked to clients).

There are no metrics or distributed traces. Adding OpenTelemetry spans around the three agent
stages would be a small, high-value next step.

---

## 9. Failure modes (and what happens)

| Failure | Behaviour | Mitigation in this repo |
| --- | --- | --- |
| Empty index / no matches | Synthesizer returns "no relevant information" with 0 citations | coverage gate + `tests/test_retrieval.py` |
| LLM timeout / bad JSON | Silent fallback to extractive answer | `_parse_json` + try/except in `complete_json` |
| Visitor key outside the allow-list | `400` before any outbound request | exact-match `LLM_ALLOWED_BASE_URLS` |
| Visitor key rejected / out of quota | `400` / `429` from `/llm/verify`; chat falls back silently | provider status mapping in `byok.py` |
| BYOK disabled by the operator | `403` on key-bearing requests; UI hides the panel | `LLM_BYOK_ENABLED` + health flag |
| Scanned PDF (no text layer) | `value_error: No extractable text found` → `status=failed` | Extension check + error surfaced in the UI |
| File > 50 MB | `413` before touching disk | size check |
| Duplicate upload | `409` with the existing document id; nothing created | SHA-256 hash + partial unique index |
| Duplicate upload with `?replace=true` | Old document, chunks and vectors removed, then the new one indexed | shared `_remove_document()` helper |
| Embedding dimension changed while a store exists | Ingestion fails with an explicit "dimension changed" message instead of mixing vectors | `dim` array in `vectors.npz` |
| Corrupt `vectors.npz` | Boot continues with an empty store; a warning is logged | `try/except` in `LocalVectorStore._load` |
| Burst of automated calls | `429` + `Retry-After` before embedding/LLM work starts | per-IP token bucket on search/chat/upload/auth |
| Backend down | Frontend proxy returns `502` with a readable detail; UI shows a banner | proxy try/catch |
| Expired or deactivated session | `401`; the account panel asks for a fresh sign-in | TTL + `is_active` check on every request |
| Missing or stale CSRF token | `403` before any work runs | double-submit hash compare |
| `DATABASE_URL` unreachable at boot | startup/health fails loudly instead of silently using SQLite | explicit `RuntimeError`, no fallback |
| Supabase project paused / `DATABASE_URL` unreachable | DB-backed calls fail; health reports `degraded` | documented; wake the project, never a silent SQLite fallback |
| Process restarts mid-ingestion | Document stuck in `processing` | *Not handled* — needs a reaper/queue |
| Redeploy on Render | `/tmp/data` wipes the vector file; relational data survives when `DATABASE_URL` is set | Postgres in the Blueprint + re-seed vectors (or Qdrant) |
| Large corpus in local store | Linear scan latency | Switch to Qdrant |
| Concurrency | SQLite + NPZ writes serialised; ingestion thread per upload | Single-instance assumption, no locks across processes |

---

## 10. Supabase Auth and user management (spec 005)

The platform supports two identity providers behind a single facade
(:mod:`app.identity`). The local provider is the spec-004 implementation
(scrypt + server-side sessions); the Supabase provider delegates credentials
to GoTrue and keeps a `profiles` read model for search, pagination and instant
authorisation checks.

```
Browser ── same-origin ──▶ Next.js proxy ──▶ FastAPI
                                     │
                     ┌───────────────┼────────────────────────┐
                     ▼               ▼                        ▼
            identity/local.py  identity/supabase.py       db.py (SQLite/PG)
            scrypt + sessions   GoTrue REST + JWT          documents, chunks,
            (dev/tests/offline)  + profiles read model     queries, traces,
                                                              profiles
                                     │
                                     ▼
                            Supabase Auth (GoTrue)
                            Supabase Postgres (pooler)
```

### 10.1 Token and cookie model (Supabase mode)

| Cookie | Flags | Contents |
| --- | --- | --- |
| `eais_access` | HttpOnly, SameSite=Lax, Secure in production | Supabase access JWT (1 h) |
| `eais_refresh` | HttpOnly, SameSite=Lax, Secure in production | rotating refresh token |
| `eais_csrf` | readable, same flags minus HttpOnly | random 24-byte token |

- **Verification**: local, with `PyJWT`. HS256 uses `SUPABASE_JWT_SECRET`; asymmetric
  keys use the project JWKS (`…/auth/v1/.well-known/jwks.json`), cached by
  `PyJWKClient`. Required claims: `exp`, `sub`; `aud=authenticated`; `iss` when known.
- **Refresh**: the auth dependency sees an expired access cookie plus a refresh
  cookie, calls `POST /token?grant_type=refresh_token`, writes the rotated pair
  onto the outgoing response, and continues. Rotation is invisible to the
  browser and to SSE streams.
- **CSRF**: double submit without server state — the header must equal the
  readable cookie, and both must exist. The token is issued at login/register/
  demo and deliberately *not* rotated on refresh (the client caches it).
- **Logout**: refresh once if needed, then `POST /logout` with the access token
  and `scope=local`, then clear all three cookies. Idempotent.

### 10.2 Profiles read model

GoTrue's admin list supports only `page`/`perPage` — no search, no filtering.
Listing therefore reads a local projection that is upserted whenever the
platform learns about a user:

```sql
CREATE TABLE profiles (
  id TEXT PRIMARY KEY,          -- Supabase auth.users.id
  email TEXT,
  role TEXT NOT NULL DEFAULT 'viewer',
  display_name TEXT,
  is_guest INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_sign_in_at TEXT
);
```

- Written on login, register, demo, admin create, admin update and admin sync.
- Missing row (user created in the Supabase dashboard) → upserted from the JWT
  claims on first authenticated request.
- **Authorisation reads the profile**, so a demotion or deactivation is
  effective on the next request instead of after the JWT expires.
- Search uses `LOWER(...) LIKE` on both dialects (portable, no `ILIKE`).
- Supabase stays the source of truth; `POST /auth/users/sync` repairs drift by
  pulling up to `SYNC_MAX_PAGES × 1000` users.

### 10.3 Admin API

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/auth/users` | `page`, `page_size`, `q`, `include_guests`; reads `profiles` |
| `POST` | `/auth/users` | create with an explicit role (existing route, now also Supabase) |
| `PATCH` | `/auth/users/{id}` | `{role?, is_active?}` |
| `POST` | `/auth/users/{id}/password-reset` | `202`; `501` in local mode |
| `DELETE` | `/auth/users/{id}` | guests only |
| `POST` | `/auth/users/sync` | pull GoTrue → profiles |

Guards in one place (`_guard_target`): not yourself, never the last active admin,
never an API-key principal, and delete is guest-only. Violations are `409` with a
readable detail.

The recovery flow is completed by the public `POST /auth/password-reset`
(`{access_token, password}`, rate limited like the other auth routes): the token
is the credential, the server forwards it to GoTrue `PUT /user` once and returns
`204`. Local mode answers `501`, so the admin panel hides the action.

### 10.4 Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTH_PROVIDER` | auto | `supabase` when `SUPABASE_URL` is set, else `local` |
| `SUPABASE_URL` | empty | project URL, e.g. `https://abcd.supabase.co` |
| `SUPABASE_ANON_KEY` | empty | publishable/anon key for password, refresh, anonymous and recover calls |
| `SUPABASE_SERVICE_ROLE_KEY` | empty | **server only**; admin API and bootstrap |
| `SUPABASE_JWT_SECRET` | empty | HS256 verification (legacy projects) |
| `SUPABASE_JWKS_URL` | derived | override the discovery endpoint |
| `SUPABASE_TIMEOUT_SECONDS` | `15` | HTTP timeout for GoTrue calls |
| `DATABASE_URL` | empty | `postgresql://...` Supabase pooler for durable data |
| `PASSWORD_RESET_REDIRECT_TO` | empty | recovery-email destination (`https://<web>/auth/reset`); the Supabase Site URL is the fallback |

Supabase deployment notes: use the **transaction pooler** URL (port 6543); the
data layer sets `prepare_threshold=0` for pooler hosts. The direct URL (5432) is
the fallback if the pooler is unavailable.

### 10.5 Failure behaviour

| Situation | Result |
| --- | --- |
| Supabase configured but service key missing | login works; admin routes `503`; health says `admin_api:false` |
| Access token expired, refresh valid | transparent rotation, request proceeds |
| Refresh rejected (revoked/banned) | cookies cleared, `401` |
| JWT signed with an unknown key | `401`, never a fallback |
| GoTrue unreachable | `502`/`503` with a readable detail; local data untouched |
| Anonymous sign-ins disabled in the project | `/auth/demo` → `403`; UI hides the guest button via health |
| Account disabled in `profiles` | `401` on the next request |
| Last active admin demotion | `409` with an explicit message |
| Password reset for an unknown address | `202` (no enumeration) |
| Local mode password reset | `501` (no email transport) |

---

## 11. Scaling path

1. **Persistence** — Postgres for `documents/chunks/queries/users/sessions` is done; object
   storage for originals is the next step.
2. **Vectors** — Qdrant (already supported) or pgvector to keep one datastore.
3. **Ingestion** — move `ingest_document` to a worker (RQ/Celery/Arq) with retries and a
   `processing → failed` reaper.
4. **Retrieval** — cross-encoder rerank on the top 50, cached embeddings, and BM25 corpus
   statistics moved to Postgres full-text (`tsvector` / `ar` config) instead of in-process.
5. **Answering** — stream tokens straight from the LLM instead of chunking a finished string;
   add tool calls for "list my documents".
6. **Ops** — move the in-memory rate limiter and query cache to Redis, add OpenTelemetry,
   per-document ACLs, and a CI job that runs `scripts/evaluate.py` against a fixture corpus so
   retrieval regressions fail the build.

None of these require changing the API contract, which is the point of the module boundaries.

---

## 12. Testing strategy

`backend/tests/test_api.py` exercises the real app through `TestClient` with a temp `DATA_DIR`:

1. health + readiness
2. 401 without a key
3. full path: upload → ingestion completes synchronously under TestClient → search finds the
   leave policy → chat returns an answer with citations
4. any signed-in role can upload; only an admin can delete (403 otherwise)
5. unsupported extension rejected (400)
6. SSE emits `token` and `done`
7. history is paginated
8. listing + deletion (204 then 404)

`backend/tests/test_retrieval.py` pins tokenisation, the coverage gate and honest abstention.
`backend/tests/test_sections.py` pins section-title anchoring (heading → body, no caption),
heading parsing, TOC filtering and the Arabic PDF visual-order round trip. Spec 002 adds
`test_store.py` (binary round trip, legacy migration, ranking, 5,000-vector load/search),
`test_dedupe.py` (409, replace, failed re-upload, delete-during-ingestion cleanup),
`test_docx_pages.py` (explicit and rendered page breaks, table pages), `test_cache.py`
(hit/miss/invalidation/copy isolation), `test_ratelimit.py` (bucket maths + HTTP 429) and
`test_request_id.py` (echo/generate/log correlation). Spec 003 adds `test_byok.py` (override,
allow-list, secrecy, provider errors). Spec 004 adds `test_auth.py` (demo guests, public and
invite-gated registration, login/logout, identical auth-failure messages, CSRF, role enforcement,
deactivation, session expiry, token hashing, API-key compatibility, admin bootstrap and an
opt-in Postgres round trip). Spec 005 adds `test_identity_supabase.py` (a stubbed GoTrue through
`httpx.MockTransport`: password grant, refresh rotation, anonymous signup, admin create/update/
ban/recover/delete, JWT verification, cookie handling, disabled accounts and admin routes) and
`test_admin_users.py` (list/search/pagination on the local provider, self and last-admin guards,
guest-only deletion, reset `501`, sync, CSRF and API-key rules). The suite is 132 tests (plus 1
skipped without `TEST_DATABASE_URL`) and runs in a few seconds against a temp database.

Frontend verification is `next build`, which runs ESLint and `tsc --noEmit`. There are no
component tests; that is the largest testing gap for a portfolio follow-up.

---

## 13. Traceability to the spec

| Spec artifact | Implementation |
| --- | --- |
| `spec.md` user stories | chat with citations, document management, Arabic/RTL UI, RBAC |
| `plan.md` phases | scaffold → ingestion → retrieval → agents → API → UI → deploy |
| `data-model.md` entities | `db.py` schema, payload contract in `store.py` |
| `contracts/openapi.yaml` | `api.py` routes, `schemas.py` payloads |
| `contracts/agent-interfaces.yaml` | `agents.py` Researcher/Retriever/Synthesizer |
| `quickstart.md` | README quickstart + `sample-data/` |
| `tasks.md` (118 tasks) | phase-by-phase checklist used to build this repo |
| `specs/002-performance-and-safety/` | binary vector store, duplicate detection, DOCX pages, query cache, rate limits, request ids |
| `specs/003-byok-llm/` | request-scoped visitor key, base-URL allow-list, verification endpoint, UI key panel |
| `specs/004-accounts-postgres/` | scrypt accounts, server-side sessions, CSRF, guests, portable Postgres layer, auth UI |
| `specs/005-supabase-auth-admin/` | Supabase Auth (GoTrue), JWT verification, profiles read model, admin panel, Supabase sync, Postgres pooler safety |
| `specs/006-gemini-embeddings/` … `specs/008-remote-embedding-service/` | optional embedding backends behind one interface |
| `specs/009-retrieval-and-ops-hardening/` | per-document retrieval, read-only consistency tools, account lockout |
| `specs/010-optional-byok-chat-hint/` | non-blocking BYOK hint and the optional `REQUIRE_CHAT_BYOK` flag |
| `specs/011-bolt-design-refresh/` | responsive workspace shell and five real-API views; visual reference only |

