# Implementation Plan: Bring-Your-Own-Key LLM

**Spec**: [`spec.md`](./spec.md) · **Branch**: `003-byok-llm` · **Date**: 2026-11-15

## Technical approach

A request-scoped `LLMSettings` value object, carried in a `ContextVar`, and
consumed by the existing `LLMClient`. Nothing is stored; the context manager
restores the previous value even when the pipeline raises.

```
Browser (sessionStorage)
  └─ X-LLM-API-Key / X-LLM-Model / X-LLM-Base-URL
       └─ Next.js proxy (forwards exactly these three headers)
            └─ FastAPI dependency `user_llm()`  → validates the allow-list
                 └─ Orchestrator.run(llm_config=…)  → `using_llm()` context
                      └─ LLMClient.complete_json() → resolve_llm()
```

### Why a ContextVar instead of threading a parameter everywhere

`plan_query` and `synthesize` sit several calls below `Orchestrator.run`. A
context manager around `run()` keeps the public signatures of the agents module
unchanged and is safe for both the streaming and the blocking paths, because
the stream generator calls `run()` inside the same function invocation.

### Validation rules (all before any outbound request)

| Field | Rule | Failure |
| --- | --- | --- |
| key | 1–200 chars, no whitespace, no control chars | `400` |
| model | `^[A-Za-z0-9._:/@+-]{1,120}$` | `400` |
| base URL | normalised (lowercase host, no trailing `/`) and present in `LLM_ALLOWED_BASE_URLS` | `400` |

Messages never contain the key. The request-id middleware already logs only
method/path/status, so no header logging change is required.

### Verification endpoint

`POST /api/v1/llm/verify` with the same three headers:

1. `GET {base}/models` (10 s timeout). `200` → `{ok: true, provider, model, models}`.
2. `404/405` (provider has no models route) → one `chat/completions` call with
   `max_tokens: 1`, reporting `checked: "completion"`.
3. `401/403` → `400` "provider rejected the key"; `429` → `429` with the
   provider's retry hint; network error → `502`.

### Frontend

- `lib/llm.ts` — read/write/clear `sessionStorage["eais-llm-key"]`, build the
  three headers.
- `components/LlmKeyPanel.tsx` — provider select (OpenAI / Groq / OpenRouter),
  model field, verify + save + forget, inline status, explicit warning that the
  key transits the server and is forgotten when the tab closes.
- `ChatInterface` — key icon with a state dot, a small "using your key" chip,
  and the panel mounted above the message list.
- `chatStream` and `verifyLlmKey` attach the headers; documents/search never do.

### Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `LLM_BYOK_ENABLED` | `true` | master switch; `false` hides the UI and returns `403` |
| `LLM_ALLOWED_BASE_URLS` | OpenAI, OpenRouter, Groq | comma-separated, exact match |
| `LLM_MAX_TOKENS` | `512` | applies to server and user keys |
| `RATE_LIMIT_LLM_VERIFY_PER_MINUTE` | `10` | protects the verification route |

### Testing strategy

| Test | Proves |
| --- | --- |
| `test_user_key_wins_over_server_key` | FR-002, SC-001 |
| `test_no_key_keeps_heuristic_behaviour` | FR-006 |
| `test_disallowed_base_url_is_rejected` | FR-004, SC-003 |
| `test_malformed_key_is_rejected` | edge case |
| `test_key_is_not_logged_or_persisted` | FR-003, SC-002 |
| `test_verify_reports_provider_errors` | FR-005 |
| `test_byok_can_be_disabled` | FR-007 |

The provider is always a monkeypatched `httpx`, so the suite stays offline and
deterministic.

### Risks

| Risk | Mitigation |
| --- | --- |
| Key leaking through an exception message | every failure path returns a fixed string; tests scan logs/traces |
| SSRF via base URL | allow-list, exact match, no redirects followed |
| Provider latency on a 0.1 CPU instance | 30 s cap + heuristic fallback |
| User key burning the operator's quota | impossible: the key is the user's, and `LLM_API_KEY` is never used when a user key is present |
| Confusing the modes in the UI | one chip states which mode answered: `your key`, `server key` (admins), `key required`, or `offline` |
