---
description: "Task list for Bring-Your-Own-Key LLM (spec 003)"
---

# Tasks: Bring-Your-Own-Key LLM

**Input**: [`spec.md`](./spec.md) · [`plan.md`](./plan.md)

## Phase 1: Contracts and configuration

- [X] T001 Write `spec.md`, `plan.md`, `data-model.md` and the OpenAPI delta
- [X] T002 Add `LLM_BYOK_ENABLED`, `LLM_ALLOWED_BASE_URLS`, `LLM_MAX_TOKENS`
      and `RATE_LIMIT_LLM_VERIFY_PER_MINUTE` to `config.py` and `.env.example`

## Phase 2: Backend (tests first)

- [X] T003 Write failing tests in `backend/tests/test_byok.py` (override,
      heuristic fallback, allow-list, malformed key, no logging, verify,
      disable switch)
- [X] T004 Add `backend/app/byok.py`: `LLMSettings`, `resolve_llm()`,
      `using_llm()`, `validate_user_llm()`, `verify_key()`
- [X] T005 Make `LLMClient` read `resolve_llm()` per call; send `max_tokens`
      and respect the per-request timeout (`agents.py`)
- [X] T006 Add `llm_config` to `Orchestrator.run` and report
      `llm_source` in the trace (`agents.py`)
- [X] T007 Add the `user_llm` dependency, `POST /api/v1/llm/verify`, the
      verify rate limit, and health reporting (`api.py`, `ratelimit.py`)
- [X] T008 Update `specs/001…/contracts/openapi.yaml` and add
      `contracts/openapi.delta.yaml`

## Phase 3: Frontend

- [X] T009 Add `lib/llm.ts` (sessionStorage, header builder)
- [X] T010 Attach the headers in `chatStream` and add `verifyLlmKey` (`lib/api.ts`)
- [X] T011 Add `components/LlmKeyPanel.tsx` and wire it into
      `ChatInterface` with a mode chip and a forget action
- [X] T012 Add Arabic/English copy (`lib/copy.ts`)
- [X] T013 Forward the three headers in the Next.js proxy
- [X] T014 `node node_modules/typescript/bin/tsc --noEmit` and `next build`
      pass

## Phase 4: Documentation and verification

- [X] T015 Update `README.md` (usage, security posture, env table) and
      `specs/001…/quickstart.md`
- [X] T016 Re-run the evaluation harness (no key header) and confirm the
      heuristic numbers are unchanged
- [X] T017 `pytest` green; commit and push to `origin main`

**Independent test**: `pytest backend/tests/test_byok.py -q`

> T016 note: the thesis corpus (final.docx) is not in the repo, so the 28-question
> baseline cannot be replayed. A 5-question smoke run over sample-data/ with no key
> returned hit@1 1.000 and abstention 1.000, confirming the heuristic path is unchanged.
