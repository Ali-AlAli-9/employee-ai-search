# Project Constitution: Employee AI Search Platform

**Version**: 1.0 | **Date**: 2026-11-13 | **Branch**: `001-employee-ai-search-platform`

## Core Principles

### 1. Code Quality First
- **Type Safety**: All Python code must have type hints (mypy strict mode). All TypeScript must be strict.
- **Linting**: Zero tolerance for linting errors (ruff for Python, ESLint for TypeScript).
- **Formatting**: Automated formatting (ruff format, prettier) - no manual formatting debates.
- **Complexity**: Cyclomatic complexity < 10 per function. Functions > 50 lines must be split.

### 2. Test-Driven Development (TDD)
- **Red-Green-Refactor**: Tests written FIRST, must FAIL before implementation.
- **Coverage Target**: >80% for core pipeline (ingestion, search, agents). >60% overall.
- **Test Pyramid**: Unit tests (fast, isolated) > Integration tests > Contract tests > E2E tests.
- **Independent Tests**: Each user story independently testable via API.

### 3. Maintainability & Architecture
- **Clean Architecture**: Separation of concerns - API layer, Service layer, Domain layer, Infrastructure layer.
- **Dependency Inversion**: Depend on abstractions (interfaces), not concretions.
- **Single Responsibility**: Each module/class/function has one reason to change.
- **Explicit over Implicit**: Clear naming, no magic, configuration over convention.

### 4. Security by Default
- **Secrets Management**: Zero secrets in code. All via environment variables.
- **Input Validation**: All external input validated at API boundary (Pydantic/Zod).
- **Authentication**: API key required for all endpoints except health checks.
- **Authorization**: Role-based access control (RBAC) enforced at API and service layer.
- **Dependency Scanning**: Automated vulnerability scanning in CI (pip-audit, npm audit).

### 5. Observability & Reliability
- **Structured Logging**: JSON logs with request_id, trace_id, user_id, latency.
- **Health Checks**: Liveness (/health) and Readiness (/health/ready) endpoints mandatory.
- **Error Handling**: Graceful degradation. Never crash on external API failures.
- **Retries & Timeouts**: Exponential backoff for external calls. Configurable timeouts.
- **Metrics**: Prometheus-compatible metrics for latency, errors, throughput.

### 6. Documentation as Code
- **API Docs**: OpenAPI/Swagger auto-generated from code. Always current.
- **Architecture Decisions**: ADRs (Architecture Decision Records) for significant choices.
- **README**: Comprehensive quickstart, architecture overview, troubleshooting.
- **Inline Docs**: Docstrings for all public functions/classes. Type hints serve as documentation.

## Technical Standards

### Python (Backend)
- **Version**: 3.11+
- **Framework**: FastAPI with async/await
- **Database**: SQLAlchemy 2.0 (async) + Alembic migrations
- **Vector DB**: Qdrant client (async)
- **ML**: sentence-transformers, langchain/langgraph for agents
- **Testing**: pytest + pytest-asyncio, httpx for API tests
- **Quality**: ruff (lint/format), mypy (strict), pytest-cov

### TypeScript (Frontend)
- **Version**: 5.x with strict mode
- **Framework**: Next.js 14 (App Router) + React 18
- **Styling**: Tailwind CSS + shadcn/ui
- **State**: React Query (TanStack Query) + React Hook Form + Zod
- **Testing**: Vitest (unit), Playwright (E2E)
- **Quality**: ESLint + Prettier, TypeScript strict

### Infrastructure
- **Containerization**: Multi-stage Dockerfiles (build → runtime)
- **Orchestration**: docker-compose (local), Render (production)
- **Database**: PostgreSQL 15 (Render managed)
- **Vector Store**: Qdrant (Render private service or Qdrant Cloud)
- **CI/CD**: GitHub Actions (lint, test, build, deploy)

## Development Workflow

### Branching Strategy
- `main`: Production-ready, protected, deployable
- `feature/*`: Short-lived feature branches from main
- `fix/*`: Bug fixes from main
- No long-running development branches

### Commit Standards
- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- **Atomic Commits**: One logical change per commit
- **Signed Commits**: GPG signed for main branch

### Pull Request Process
1. All CI checks pass (lint, type-check, test, build)
2. Code review by at least 1 maintainer
3. No merge conflicts with main
4. Related issue linked
5. Squash merge to main

### Release Process
- Semantic versioning (MAJOR.MINOR.PATCH)
- CHANGELOG.md updated with each release
- Git tags for each version
- Automated deployment on tag push

## Project-Specific Rules

### AI/ML Specific
- **Model Versioning**: Embedding model name and version pinned in config
- **Prompt Versioning**: Agent prompts stored as versioned templates
- **Evaluation**: Automated eval pipeline for answer quality (RAGAS or custom)
- **Fallback**: Local model fallback when API providers unavailable
- **Cost Awareness**: Track token usage per query. Optimize for free tier.

### Data Handling
- **Privacy**: No PII in logs. Document content not logged.
- **Retention**: Search queries 90 days, Agent traces 90 days, Documents indefinite.
- **Deletion**: GDPR-compliant user data deletion on request.

### Performance Budgets
- **API Latency**: p95 < 3s (warm), < 10s (cold start)
- **Frontend LCP**: < 2s
- **Bundle Size**: < 200KB gzipped (frontend)
- **Memory**: < 400MB per service (Render free tier limit 512MB)
- **Ingestion**: 100-page PDF < 60s

## Governance

### Constitution Amendments
- Requires: 2 maintainer approvals + 7-day review period
- Documented in CHANGELOG.md with rationale
- Applied to all future work (not retroactive)

### Exception Process
- Temporary exceptions allowed with: issue link, expiration date, mitigation plan
- Maximum 30 days. Must be resolved or escalated.

### Code Ownership
- **Backend**: @backend-team
- **Frontend**: @frontend-team
- **Infrastructure**: @devops-team
- **AI/ML**: @ml-team

---

**Signed**: _________________________ **Date**: _______________

**Maintainer 1**: _________________________

**Maintainer 2**: _________________________