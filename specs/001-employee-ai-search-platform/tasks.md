---
description: "Task list for Employee AI Search Platform implementation"
---

# Tasks: Employee AI Search Platform

**Input**: Design documents from `/specs/001-employee-ai-search-platform/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are MANDATORY for all user stories. Write tests FIRST, ensure they FAIL before implementation.

**Organization**: Tasks grouped by user story for independent implementation and testing.

> **Implementation note (2026-11-13):** these 118 tasks were the plan used to build the repo.
> The delivered code lives in a flatter layout (`backend/app/`, `frontend/{app,components,lib}/`)
> and swaps PostgreSQL/Qdrant for SQLite + a file-backed store by default. See the status table
> at the top of [`plan.md`](./plan.md) and [`ARCHITECTURE.md`](../../ARCHITECTURE.md) for the
> reasons. Paths below are the original plan, not the final tree.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story this task belongs to (US1-US6)
- Include exact file paths in descriptions

## Path Conventions

- **Web app**: `backend/src/`, `frontend/src/`
- Paths shown below assume web app structure

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, Docker, linting, CI/CD foundation

- [ ] T001 Create repository structure per implementation plan (backend/, frontend/, docker-compose.yml)
- [ ] T002 Initialize backend: FastAPI project with pyproject.toml, ruff, mypy, pytest config
- [ ] T003 Initialize frontend: Next.js 14 (App Router) with TypeScript, Tailwind, shadcn/ui, ESLint, Prettier
- [ ] T004 [P] Configure docker-compose.yml with backend, frontend, postgres, qdrant services
- [ ] T005 [P] Create docker-compose.prod.yml for Render deployment (multi-stage builds, no dev volumes)
- [ ] T006 [P] Setup GitHub Actions CI workflow (lint, type-check, test, build)
- [ ] T007 [P] Create .env.example with all required environment variables
- [ ] T008 [P] Add pre-commit hooks (ruff, mypy, eslint, prettier)
- [ ] T009 [P] Create README.md with project overview, quickstart, architecture diagram

**Checkpoint**: All services start with `docker-compose up`, CI passes on empty commit

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure required by ALL user stories

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T010 Create PostgreSQL models (User, Document, Chunk, SearchQuery, AgentTrace) in `backend/src/models/`
- [ ] T011 Create database session management in `backend/src/database/session.py`
- [ ] T012 Create Alembic migration environment and initial migration
- [ ] T013 Implement configuration management in `backend/src/core/config.py` (pydantic-settings)
- [ ] T014 Implement security: API key hashing, validation, RBAC in `backend/src/core/security.py`
- [ ] T015 Create Pydantic schemas for all API contracts in `backend/src/schemas/`
- [ ] T016 Implement exception handling and custom exceptions in `backend/src/core/exceptions.py`
- [ ] T017 Create Qdrant client wrapper in `backend/src/services/qdrant_service.py`
- [ ] T018 Implement embedding service in `backend/src/services/embedding_service.py` (sentence-transformers)
- [ ] T019 Create base FastAPI app with middleware, CORS, logging in `backend/src/main.py`
- [ ] T020 Implement health check endpoints (/health, /health/ready) in `backend/src/api/v1/health.py`
- [ ] T021 [P] Create API key authentication dependency in `backend/src/api/dependencies.py`
- [ ] T022 [P] Setup frontend API client in `frontend/src/lib/api.ts` with SSE support
- [ ] T023 [P] Create TypeScript types matching backend schemas in `frontend/src/types/`
- [ ] T024 [P] Configure Tailwind with RTL support (tailwindcss-rtl plugin) in `frontend/tailwind.config.ts`
- [ ] T025 [P] Setup shadcn/ui components (Button, Input, Card, ScrollArea, Dropdown, Avatar)

**Checkpoint**: Backend starts, connects to DB/Qdrant, health checks pass. Frontend builds, TypeScript compiles.

---

## Phase 3: User Story 1 - Document Ingestion & Indexing (Priority: P1) 🎯 MVP

**Goal**: Upload, parse, chunk, embed, and index documents into Qdrant

**Independent Test**: Upload PDF → verify document appears in list → verify chunks in Qdrant with embeddings

### Tests for User Story 1 (Write FIRST, ensure FAIL)

- [ ] T026 [P] [US1] Contract test: POST /api/v1/documents/upload in `backend/tests/contract/test_documents_upload.py`
- [ ] T027 [P] [US1] Contract test: GET /api/v1/documents in `backend/tests/contract/test_documents_list.py`
- [ ] T028 [P] [US1] Contract test: DELETE /api/v1/documents/{id} in `backend/tests/contract/test_documents_delete.py`
- [ ] T029 [P] [US1] Integration test: Full ingestion pipeline in `backend/tests/integration/test_ingestion_pipeline.py`

### Implementation for User Story 1

- [ ] T030 [P] [US1] Create document upload endpoint in `backend/src/api/v1/documents.py`
- [ ] T031 [P] [US1] Implement document parsers in `backend/src/services/ingestion/parsers.py` (PDF, DOCX, TXT, MD)
- [ ] T032 [P] [US1] Implement text chunking in `backend/src/services/ingestion/chunker.py` (512 tokens, 50 overlap)
- [ ] T033 [P] [US1] Implement embedding generation in `backend/src/services/ingestion/embedder.py`
- [ ] T034 [P] [US1] Implement Qdrant indexing in `backend/src/services/ingestion/indexer.py`
- [ ] T035 [US1] Create ingestion orchestrator in `backend/src/services/ingestion/orchestrator.py` (async, background task)
- [ ] T036 [US1] Add document status tracking (pending→processing→completed/failed) with error handling
- [ ] T037 [US1] Implement document listing with pagination/filtering
- [ ] T038 [US1] Implement document deletion (PostgreSQL + Qdrant cleanup)
- [ ] T039 [P] [US1] Create DocumentUpload component in `frontend/src/components/documents/DocumentUpload.tsx`
- [ ] T040 [P] [US1] Create DocumentList component in `frontend/src/components/documents/DocumentList.tsx`
- [ ] T041 [P] [US1] Add document management page in `frontend/src/app/documents/page.tsx`

**Checkpoint**: Upload PDF → appears in list → chunks searchable in Qdrant → deletion works

---

## Phase 4: User Story 2 - Semantic Search & Retrieval (Priority: P1)

**Goal**: Hybrid search (vector + keyword) with cross-encoder reranking

**Independent Test**: Index known docs → query → verify relevant chunks returned with scores

### Tests for User Story 2

- [ ] T042 [P] [US2] Contract test: POST /api/v1/search in `backend/tests/contract/test_search.py`
- [ ] T043 [P] [US2] Integration test: Hybrid search accuracy in `backend/tests/integration/test_hybrid_search.py`
- [ ] T044 [P] [US2] Unit test: Chunker, embedder, reranker in `backend/tests/unit/test_search_components.py`

### Implementation for User Story 2

- [ ] T045 [P] [US2] Create search endpoint in `backend/src/api/v1/search.py`
- [ ] T046 [P] [US2] Implement vector search in `backend/src/services/search_service.py` (Qdrant cosine similarity)
- [ ] T047 [P] [US2] Implement keyword search (BM25) in `backend/src/services/search_service.py`
- [ ] T048 [P] [US2] Implement hybrid fusion (RRF or weighted) in `backend/src/services/search_service.py`
- [ ] T049 [P] [US2] Implement cross-encoder reranking in `backend/src/services/reranker.py`
- [ ] T050 [US2] Add search filters (document_ids, content_types, date_range)
- [ ] T051 [US2] Implement search result caching (optional, Redis)
- [ ] T052 [P] [US2] Create SearchTest component in `frontend/src/components/search/SearchTest.tsx` (dev only)

**Checkpoint**: Search returns relevant chunks with hybrid scores, reranking improves precision

---

## Phase 5: User Story 3 - Multi-Agent Answer Synthesis (Priority: P1)

**Goal**: Researcher → Retriever → Synthesizer agent pipeline with streaming

**Independent Test**: Ask complex question → verify synthesized answer with citations from multiple sources

### Tests for User Story 3

- [ ] T053 [P] [US3] Contract test: POST /api/v1/chat (streaming) in `backend/tests/contract/test_chat_stream.py`
- [ ] T054 [P] [US3] Contract test: POST /api/v1/chat (non-streaming) in `backend/tests/contract/test_chat_sync.py`
- [ ] T055 [P] [US3] Integration test: Full agent pipeline in `backend/tests/integration/test_agent_pipeline.py`
- [ ] T056 [P] [US3] Unit test: Researcher agent in `backend/tests/unit/test_researcher_agent.py`
- [ ] T057 [P] [US3] Unit test: Retriever agent in `backend/tests/unit/test_retriever_agent.py`
- [ ] T058 [P] [US3] Unit test: Synthesizer agent in `backend/tests/unit/test_synthesizer_agent.py`

### Implementation for User Story 3

- [ ] T059 [P] [US3] Create Researcher agent in `backend/src/agents/researcher.py` (query planning, sub-queries)
- [ ] T060 [P] [US3] Create Retriever agent in `backend/src/agents/retriever.py` (executes search)
- [ ] T061 [P] [US3] Create Synthesizer agent in `backend/src/agents/synthesizer.py` (answer + citations)
- [ ] T062 [P] [US3] Define agent I/O schemas in `backend/src/agents/schemas.py` (Pydantic models)
- [ ] T063 [US3] Create Orchestrator in `backend/src/agents/orchestrator.py` (coordinates pipeline, retries, fallbacks)
- [ ] T064 [US3] Implement chat endpoint with SSE streaming in `backend/src/api/v1/chat.py`
- [ ] T065 [US3] Add conversation history support (last 10 messages)
- [ ] T066 [US3] Implement chat history endpoint in `backend/src/api/v1/chat.py`
- [ ] T067 [US3] Add AgentTrace logging for all agent steps
- [ ] T068 [P] [US3] Create useChat hook in `frontend/src/lib/hooks/useChat.ts` (SSE handling)
- [ ] T069 [P] [US3] Create StreamingResponse component in `frontend/src/components/chat/StreamingResponse.tsx`
- [ ] T070 [P] [US3] Create CitationCard component in `frontend/src/components/chat/CitationCard.tsx`

**Checkpoint**: Chat returns synthesized answer with inline citations, streaming works token-by-token

---

## Phase 6: User Story 4 - Web Interface (Priority: P2)

**Goal**: Polished Next.js/React chat UI with RTL Arabic support

**Independent Test**: Open app → ask question → see streaming answer with clickable citations

### Tests for User Story 4

- [ ] T071 [P] [US4] Component test: ChatInterface in `frontend/tests/unit/ChatInterface.test.tsx`
- [ ] T072 [P] [US4] Component test: MessageList in `frontend/tests/unit/MessageList.test.tsx`
- [ ] T073 [P] [US4] E2E test: Full chat flow in `frontend/tests/e2e/chat-flow.spec.ts`
- [ ] T074 [P] [US4] E2E test: Document upload in `frontend/tests/e2e/document-upload.spec.ts`
- [ ] T075 [P] [US4] Visual regression: RTL layout in `frontend/tests/visual/rtl-layout.spec.ts`

### Implementation for User Story 4

- [ ] T076 [P] [US4] Create main layout in `frontend/src/app/layout.tsx` (Header, Sidebar, RTL toggle)
- [ ] T077 [P] [US4] Create chat page in `frontend/src/app/page.tsx` (ChatInterface)
- [ ] T078 [P] [US4] Create ChatInterface component in `frontend/src/components/chat/ChatInterface.tsx`
- [ ] T079 [P] [US4] Create MessageList with auto-scroll in `frontend/src/components/chat/MessageList.tsx`
- [ ] T080 [P] [US4] Create MessageInput with auto-resize in `frontend/src/components/chat/MessageInput.tsx`
- [ ] T081 [P] [US4] Implement citation rendering with click-to-view-source
- [ ] T082 [P] [US4] Add document sidebar (upload, list, delete) in `frontend/src/components/layout/Sidebar.tsx`
- [ ] T083 [P] [US4] Implement RTL toggle (English/Arabic) with localStorage persistence
- [ ] T084 [P] [US4] Add loading states, error boundaries, toast notifications
- [ ] T085 [P] [US4] Implement responsive design (mobile < 768px, tablet, desktop)
- [ ] T086 [P] [US4] Add accessibility (ARIA labels, keyboard nav, focus management)

**Checkpoint**: Beautiful, responsive chat UI with full RTL support, all interactions work

---

## Phase 7: User Story 5 - Render Deployment (Priority: P2)

**Goal**: Production Docker images, Render configuration, health checks

**Independent Test**: Deploy to Render → all services healthy → app responds to queries

### Tests for User Story 5

- [ ] T087 [P] [US5] Integration test: Docker build in `backend/tests/integration/test_docker_build.py`
- [ ] T088 [P] [US5] Smoke test: Deployed endpoint health in `backend/tests/integration/test_render_health.py`

### Implementation for User Story 5

- [ ] T089 [P] [US5] Optimize backend Dockerfile (multi-stage, non-root user, layer caching)
- [ ] T090 [P] [US5] Optimize frontend Dockerfile (multi-stage, standalone output, compression)
- [ ] T091 [US5] Configure Render service connections (backend ↔ postgres ↔ qdrant)
- [ ] T092 [US5] Set up Render environment variables (secrets for API keys)
- [ ] T093 [US5] Configure health check endpoints for Render readiness/liveness probes
- [ ] T094 [US5] Add GitHub Actions deploy workflow (on merge to main)
- [ ] T095 [US5] Implement graceful shutdown (SIGTERM handling) in backend
- [ ] T096 [US5] Add cold-start optimization (preload embedding model on startup)
- [ ] T097 [US5] Configure Qdrant persistence (Render disk or Qdrant Cloud)

**Checkpoint**: `git push origin main` → Render deploys → all services green → app works

---

## Phase 8: User Story 6 - Authentication & RBAC (Priority: P3)

**Goal**: API key auth with admin/user/viewer roles

**Independent Test**: Access endpoints with different keys → verify 401/403/200 responses

### Tests for User Story 6

- [ ] T098 [P] [US6] Contract test: Auth validation in `backend/tests/contract/test_auth.py`
- [ ] T099 [P] [US6] Integration test: RBAC enforcement in `backend/tests/integration/test_rbac.py`

### Implementation for User Story 6

- [ ] T100 [P] [US6] Implement API key generation and hashing in `backend/src/services/auth.py`
- [ ] T101 [P] [US6] Create role-based dependency functions in `backend/src/api/dependencies.py`
- [ ] T102 [US6] Protect document upload with `viewer` and delete with `admin` role
- [ ] T103 [US6] Protect search/chat with user/viewer role
- [ ] T104 [US6] Add user management endpoints (admin only)
- [ ] T105 [P] [US6] Add auth context to frontend in `frontend/src/lib/auth.ts`
- [ ] T106 [P] [US6] Show/hide UI elements based on role

**Checkpoint**: Role-based access enforced at API and UI level

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Improvements affecting multiple user stories

- [ ] T107 [P] Documentation: API docs (Swagger), Architecture Decision Records in `docs/adr/`
- [ ] T108 [P] Documentation: Update README with deployment guide, troubleshooting
- [ ] T109 Code cleanup: Remove dev-only endpoints, tighten CORS, remove console.logs
- [ ] T110 Performance: Add response caching for repeated queries (Redis or in-memory)
- [ ] T111 Performance: Optimize embedding batch processing, connection pooling
- [ ] T112 [P] Security: Dependency audit (pip-audit, npm audit), fix vulnerabilities
- [ ] T113 [P] Security: Add rate limiting (slowapi) to chat/search endpoints
- [ ] T114 [P] Testing: Achieve >80% coverage on core pipeline (ingestion, search, agents)
- [ ] T115 [P] Testing: Add load test script (locust) for 10 concurrent users
- [ ] T116 Observability: Add structured logging (JSON), request tracing (request_id)
- [ ] T117 Observability: Add metrics endpoint (Prometheus format) for latency, errors, usage
- [ ] T118 [P] Quickstart validation: Run quickstart.md steps end-to-end on clean machine

---

## Dependencies & Execution Order

### Phase Dependencies

1. **Setup (Phase 1)**: No dependencies - start immediately
2. **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories
3. **User Story 1 (Phase 3)**: Depends on Foundational - Can start after T025
4. **User Story 2 (Phase 4)**: Depends on Foundational + US1 (needs indexed data) - Can parallel with US1 after T035
5. **User Story 3 (Phase 5)**: Depends on Foundational + US1 + US2 - Can parallel after T050
6. **User Story 4 (Phase 6)**: Depends on Foundational + US3 (needs chat endpoint) - Can parallel after T064
7. **User Story 5 (Phase 7)**: Depends on all previous - Can start after T070
8. **User Story 6 (Phase 8)**: Depends on Foundational - Can parallel anytime after T021
9. **Polish (Phase 9)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: Document Ingestion - Foundation for all search/chat
- **US2 (P1)**: Search & Retrieval - Requires US1 data, enables US3
- **US3 (P1)**: Multi-Agent Chat - Requires US1 + US2, enables US4
- **US4 (P2)**: Web UI - Requires US3 chat endpoint
- **US5 (P2)**: Deployment - Requires all services working
- **US6 (P3)**: Auth/RBAC - Can develop in parallel after Foundational

### Within Each User Story

1. Tests MUST be written and FAIL before implementation
2. Backend implementation before frontend integration
3. Core logic before API endpoints
4. API endpoints before frontend components
5. Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks [P] can run in parallel
- All Foundational tasks [P] can run in parallel (within Phase 2)
- Once Foundational complete: US1, US2, US3, US6 can start in parallel (if team capacity)
- All [P] tests within a story can run in parallel
- Frontend components [P] can be developed in parallel with backend endpoints

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together:
Task: "Contract test: POST /api/v1/documents/upload"
Task: "Contract test: GET /api/v1/documents"
Task: "Contract test: DELETE /api/v1/documents/{id}"
Task: "Integration test: Full ingestion pipeline"

# Launch all US1 parsers in parallel:
Task: "Implement PDF parser"
Task: "Implement DOCX parser"
Task: "Implement TXT/MD parser"

# Launch frontend components in parallel:
Task: "Create DocumentUpload component"
Task: "Create DocumentList component"
Task: "Add document management page"
```

---

## Implementation Strategy

### MVP First (User Stories 1-3 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL)
3. Complete Phase 3: User Story 1 (Document Ingestion)
4. Complete Phase 4: User Story 2 (Search)
5. Complete Phase 5: User Story 3 (Multi-Agent Chat)
6. **STOP and VALIDATE**: Test full pipeline end-to-end
7. Deploy to Render (Phase 7) for live demo
8. Then add Phase 6 (UI polish) and Phase 8 (Auth)

### Incremental Delivery

Each user story adds independent value:
- US1: Document management API
- US2: Search API
- US3: Intelligent chat API
- US4: Beautiful UI
- US5: Live deployment
- US6: Production security

### Validation Checkpoints

After each user story:
- [ ] All tests pass (unit, integration, contract)
- [ ] Story independently testable via API
- [ ] No regression in previous stories
- [ ] Performance within targets
- [ ] Documentation updated

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence