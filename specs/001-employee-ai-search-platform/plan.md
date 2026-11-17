# Implementation Plan: Employee AI Search Platform

**Branch**: `001-employee-ai-search-platform` | **Date**: 2026-11-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-employee-ai-search-platform/spec.md`

## Implementation status (2026-11-13)

The MVP described here was implemented and verified: `pytest` → 9 passed, `next build` →
compiled with lint + type checks. A few infrastructure choices changed on purpose, to keep the
whole stack runnable on the Render free tier with **zero paid services**. The original plan is
kept below as the design rationale; the delivered system lives in [`ARCHITECTURE.md`](../../ARCHITECTURE.md).

| Area | Planned | Delivered | Why |
| --- | --- | --- | --- |
| Metadata store | PostgreSQL 15 | SQLite (stdlib `sqlite3`), Postgres-compatible SQL | No managed DB on the free plan; zero ops, single container |
| Vector store | Qdrant | File-backed cosine store by default, **Qdrant adapter included** | Removes a service; `QDRANT_URL` switches it on |
| Embeddings | sentence-transformers | Deterministic hashing embedder by default, ST optional | 512 MB RAM limit; instant cold start, no model download |
| Agent framework | LangChain/LangGraph | Explicit pipeline in `backend/app/agents.py` | Three stages, one JSON call each — a framework would add weight without benefit |
| Backend layout | `backend/src/...` | Flat `backend/app/*.py` | ~1.2k LOC total; deeper nesting would be ceremony |
| Frontend UI kit | shadcn/ui, zod, swr | Hand-built Tailwind components | Full control of the RTL design, smaller bundle |
| Tests | pytest + vitest + playwright | 9 pytest end-to-end tests + `next build` | Highest-value coverage first; UI tests are the next step |

## Summary

Build a production-ready AI-powered search platform for employees using hybrid RAG (vector + keyword search with reranking) and multi-agent answer synthesis (Researcher → Retriever → Synthesizer). The system includes document ingestion pipeline, FastAPI backend with agent orchestration, Next.js/React frontend with streaming chat UI, PostgreSQL for metadata, Qdrant for vector storage, all containerized with Docker and deployed on Render free tier.

Technical approach: Modular monorepo with `backend/` (FastAPI + Python) and `frontend/` (Next.js + TypeScript). Uses sentence-transformers for local embeddings, Qdrant for vector DB, LangChain/LangGraph for agent orchestration, Server-Sent Events for streaming responses.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript 5.x (frontend), Node.js 20 LTS

**Primary Dependencies**: 
- Backend: FastAPI, Uvicorn, LangChain/LangGraph, sentence-transformers, qdrant-client, psycopg2, python-multipart, pydantic, pydantic-settings, httpx, tenacity
- Frontend: Next.js 14 (App Router), React 18, Tailwind CSS, shadcn/ui, lucide-react, zod, react-hook-form, swr
- Infrastructure: Docker, docker-compose, PostgreSQL 15, Qdrant latest

**Storage**: PostgreSQL (documents, users, chat history, metadata), Qdrant (vector embeddings with payload)

**Testing**: pytest (backend), Vitest + React Testing Library (frontend), Playwright (E2E)

**Target Platform**: Linux containers on Render (Free Tier: 512MB RAM, 0.5 CPU per service)

**Project Type**: Web application (frontend + backend + databases)

**Performance Goals**: 
- Ingestion: 100-page PDF < 60s
- Search latency (warm): < 3s to first token
- Search latency (cold): < 10s
- LCP: < 2s
- Concurrent users: 10 on free tier

**Constraints**: 
- Render free tier: 512MB RAM/service, services sleep after 15min inactivity
- Qdrant in-memory storage limited by RAM
- PostgreSQL 1GB storage limit
- No GPU - all ML inference on CPU
- LLM APIs via external providers (rate limits apply)

**Scale/Scope**: 
- 1,000 documents max (v1)
- 100 concurrent indexed chunks per document
- 100 QA pairs in test dataset
- 3 user roles (admin, user, viewer)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| Code quality: Type hints, linting, formatting | ✅ Planned | ruff, mypy, pre-commit |
| Testing: Unit + integration + contract tests | ✅ Planned | pytest, vitest, playwright |
| Maintainability: Modular architecture, clear separation | ✅ Planned | Clean architecture layers |
| Security: Auth, input validation, secrets management | ✅ Planned | API keys, RBAC, env vars |
| Documentation: README, API docs, architecture decision records | ✅ Planned | OpenAPI/Swagger, ADRs |

## Project Structure

### Documentation (this feature)

```text
specs/001-employee-ai-search-platform/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── openapi.yaml
│   └── agent-interfaces.yaml
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
employee-ai-search/
├── backend/
│   ├── src/
│   │   ├── api/                 # FastAPI routes
│   │   │   ├── v1/
│   │   │   │   ├── documents.py
│   │   │   │   ├── search.py
│   │   │   │   ├── chat.py
│   │   │   │   └── health.py
│   │   │   └── dependencies.py
│   │   ├── core/                # Core configuration & security
│   │   │   ├── config.py
│   │   │   ├── security.py
│   │   │   └── exceptions.py
│   │   ├── models/              # SQLAlchemy models
│   │   │   ├── document.py
│   │   │   ├── chunk.py
│   │   │   ├── user.py
│   │   │   └── search_query.py
│   │   ├── schemas/             # Pydantic schemas
│   │   │   ├── document.py
│   │   │   ├── search.py
│   │   │   ├── chat.py
│   │   │   └── user.py
│   │   ├── services/            # Business logic
│   │   │   ├── ingestion.py
│   │   │   ├── embedding.py
│   │   │   ├── search_service.py
│   │   │   ├── reranker.py
│   │   │   └── auth.py
│   │   ├── agents/              # Multi-agent orchestration
│   │   │   ├── researcher.py
│   │   │   ├── retriever.py
│   │   │   ├── synthesizer.py
│   │   │   ├── orchestrator.py
│   │   │   └── schemas.py
│   │   ├── database/            # DB session & initialization
│   │   │   ├── session.py
│   │   │   └── init_db.py
│   │   └── main.py              # FastAPI app entry point
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── contract/
│   │   └── conftest.py
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router pages
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx         # Main chat interface
│   │   │   ├── globals.css
│   │   │   └── api/             # API routes (proxy to backend)
│   │   ├── components/          # React components
│   │   │   ├── ui/              # shadcn/ui components
│   │   │   ├── chat/
│   │   │   │   ├── ChatInterface.tsx
│   │   │   │   ├── MessageList.tsx
│   │   │   │   ├── MessageInput.tsx
│   │   │   │   ├── CitationCard.tsx
│   │   │   │   └── StreamingResponse.tsx
│   │   │   ├── documents/
│   │   │   │   ├── DocumentList.tsx
│   │   │   │   └── DocumentUpload.tsx
│   │   │   └── layout/
│   │   │       ├── Header.tsx
│   │   │       └── Sidebar.tsx
│   │   ├── lib/                 # Utilities & hooks
│   │   │   ├── api.ts           # API client
│   │   │   ├── utils.ts
│   │   │   ├── hooks/
│   │   │   │   ├── useChat.ts
│   │   │   │   └── useDocuments.ts
│   │   │   └── validations/
│   │   │       └── chat.ts
│   │   └── types/               # TypeScript types
│   │       ├── api.ts
│   │       └── chat.ts
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── e2e/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── next.config.js
│   └── .eslintrc.json
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── README.md
├── ARCHITECTURE.md
└── LICENSE
```

**Structure Decision**: Option 2 (Web application with frontend/backend separation) selected. This matches the spec's requirement for a React/Next.js frontend and FastAPI backend with separate containers for deployment flexibility on Render.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Multi-agent orchestration (3 agents) | Core differentiator for AI Engineer portfolio; demonstrates advanced agent patterns | Single-agent RAG is standard and doesn't showcase orchestration skills |
| Hybrid search (vector + keyword + rerank) | Production-grade retrieval quality; baseline vector-only is insufficient for portfolio | Vector-only search has poor keyword matching; reranking adds measurable quality |
| Local embeddings + API LLMs | Cost optimization for free tier; demonstrates infrastructure awareness | All-API approach exceeds free tier budget; all-local exceeds RAM limits |
| Arabic RTL support | Differentiator for MENA market; shows i18n awareness | English-only is standard but less impressive for regional relevance |
| Streaming SSE responses | UX expectation for chat interfaces; demonstrates async handling | Polling is simpler but provides poor UX and higher server load |

---

## Phase 0: Research & Technology Validation

**Objective**: Validate technical choices, benchmark embedding models, test Qdrant on free tier, prototype agent orchestration.

**Deliverable**: `research.md` with findings and decisions.

**Tasks**:
- [ ] Benchmark embedding models: `all-MiniLM-L6-v2` vs `BAAI/bge-small-en-v1.5` vs `intfloat/multilingual-e5-small` (speed, quality, RAM)
- [ ] Test Qdrant memory usage with 10k vectors (768-dim) on 512MB limit
- [ ] Prototype LangGraph multi-agent flow: Researcher → Retriever → Synthesizer
- [ ] Test Render free tier cold start times for Python/Node services
- [ ] Validate Arabic RTL with Tailwind + shadcn/ui
- [ ] Compare SSE vs WebSockets for streaming (SSE chosen for simplicity)
- [ ] Research document parsers: `pymupdf` vs `pdfplumber` vs `unstructured` for PDF/DOCX
- [ ] Evaluate cross-encoder rerankers: `cross-encoder/ms-marco-MiniLM-L-6-v2` vs `BAAI/bge-reranker-base`

**Output**: Research document with benchmarks, decisions, and risk mitigation.

---

## Phase 1: Design & Contracts

**Objective**: Define data models, API contracts, agent interfaces, and quickstart guide.

**Deliverables**: `data-model.md`, `contracts/openapi.yaml`, `contracts/agent-interfaces.yaml`, `quickstart.md`

### Data Model (data-model.md)

**Entities**:
1. **Document** - id (UUID), filename, content_type, size_bytes, status (pending/processing/completed/failed), chunks_count, created_at, updated_at
2. **Chunk** - id (UUID), document_id (FK), chunk_index, text, embedding (vector), metadata (JSON: page_number, section), created_at
3. **User** - id (UUID), email, api_key_hash, role (admin/user/viewer), is_active, created_at, last_login
4. **SearchQuery** - id (UUID), query_text, user_id (FK), results_count, latency_ms, agent_trace_id (FK), created_at
5. **AgentTrace** - id (UUID), query_id (FK), agent_name, input (JSON), output (JSON), duration_ms, status (success/error), created_at

**Relationships**: Document 1:N Chunk, User 1:N SearchQuery, SearchQuery 1:1 AgentTrace

### API Contracts (contracts/openapi.yaml)

**Endpoints**:
- `POST /api/v1/documents/upload` - Upload document (multipart), returns document_id
- `GET /api/v1/documents` - List documents with pagination/filtering
- `GET /api/v1/documents/{id}` - Get document details
- `DELETE /api/v1/documents/{id}` - Delete document and chunks
- `POST /api/v1/search` - Hybrid search, returns chunks with scores
- `POST /api/v1/chat` - Multi-agent chat (streaming SSE), returns answer with citations
- `GET /api/v1/chat/history` - Get chat history for user
- `GET /api/v1/health` - Health check (liveness/readiness)

### Agent Interfaces (contracts/agent-interfaces.yaml)

**Researcher Agent**:
- Input: `{ query: string, context?: ConversationHistory }`
- Output: `{ sub_queries: string[], search_strategy: "hybrid" | "vector" | "keyword", filters?: MetadataFilters }`

**Retriever Agent**:
- Input: `{ sub_queries: string[], strategy: string, filters?: MetadataFilters, top_k: int }`
- Output: `{ chunks: ChunkWithScore[], total_found: int }`

**Synthesizer Agent**:
- Input: `{ query: string, chunks: ChunkWithScore[], conversation_history?: Message[] }`
- Output: `{ answer: string, citations: Citation[], confidence: float }`

### Quickstart (quickstart.md)

Local development setup with Docker Compose, environment variables, running tests, accessing Swagger UI, and deploying to Render.

---

## Phase 2: Task Generation

**Objective**: Generate detailed implementation tasks organized by user story.

**Deliverable**: `tasks.md` with phased tasks (see tasks template).

**Task Phases**:
1. **Setup** (Shared Infrastructure): Project scaffolding, Docker, linting, CI
2. **Foundational** (Blocking): Database models, auth, config, Qdrant client, embedding service
3. **User Story 1** (P1 - Document Ingestion): Upload API, parsers, chunking, embedding, indexing
4. **User Story 2** (P1 - Search & Retrieval): Hybrid search, reranking, search API
5. **User Story 3** (P1 - Multi-Agent Synthesis): Researcher, Retriever, Synthesizer, Orchestrator
6. **User Story 4** (P2 - Web Interface): Next.js setup, chat UI, streaming, citations, RTL
5. **User Story 5** (P2 - Render Deployment): Docker Compose prod, Render config, health checks
6. **User Story 6** (P3 - Auth & RBAC): API keys, roles, protected endpoints
7. **Polish**: Tests, documentation, performance, security hardening

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Render free tier RAM insufficient for Qdrant + embeddings | High | High | Use quantization (Qdrant), smaller embeddings (384-dim), lazy loading |
| LLM API rate limits break multi-agent flow | Medium | High | Implement retry with exponential backoff, fallback to local LLM (Ollama) |
| Cold start > 30s causes timeout | High | Medium | Optimize Docker images, pre-warm embeddings, health check endpoints |
| Arabic RTL breaks shadcn/ui components | Low | Medium | Test early, use `tailwindcss-rtl` plugin, manual fixes for complex components |
| Document parsing fails on complex PDFs | Medium | Medium | Multiple parser fallback (pymupdf → pdfplumber → unstructured), error logging |
| Qdrant persistence on Render disk unreliable | Medium | High | Regular snapshots to S3-compatible storage, graceful degradation to in-memory |

---

## Success Validation

- All P1 user stories independently testable and deployable
- CI pipeline passes on every commit
- Render deployment succeeds and serves traffic
- Load test: 10 concurrent users, 100 queries, < 5% error rate
- Security scan: 0 critical, < 5 high vulnerabilities
- Documentation complete: README, API docs, Architecture Decision Records