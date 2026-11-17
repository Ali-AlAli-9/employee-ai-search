# Data Model: Bring-Your-Own-Key LLM

**Spec**: [`spec.md`](./spec.md)

## Persisted data

**None.** This feature deliberately adds zero tables, zero columns, zero files
and zero environment-persisted user state. The reason is the whole point of the
feature: a third-party credential should not outlive the request that used it.

The only durable trace of a BYOK request is the existing `traces` row, whose
`data_json.llm_source` is `"user"` or `"server"` — a label, never a credential.

## Request-scoped value object

```python
@dataclass(frozen=True)
class LLMSettings:
    api_key: str        # never logged, never returned
    model: str          # e.g. "gpt-4o-mini"
    base_url: str       # normalised, must be in the allow-list
    timeout: float      # <= 30 s for user keys
    max_tokens: int     # LLM_MAX_TOKENS
    source: str         # "server" | "user"
```

Held in a `ContextVar` for the duration of `Orchestrator.run()` and reset by a
context manager.

## HTTP headers

| Header | Required | Validation |
| --- | --- | --- |
| `X-LLM-API-Key` | yes (to enable BYOK) | 1–200 chars, no whitespace or control chars |
| `X-LLM-Model` | no | `^[A-Za-z0-9._:/@+-]{1,120}$`; defaults to `LLM_MODEL` |
| `X-LLM-Base-URL` | no | defaults to `LLM_BASE_URL`; must exactly match an entry in `LLM_ALLOWED_BASE_URLS` |

An empty `X-LLM-API-Key` header is equivalent to omitting it.

## Browser storage

`sessionStorage["eais-llm-key"] = {"key": "...", "model": "...", "baseUrl": "..."}`

- Cleared when the tab closes.
- Cleared by the "Forget key" button.
- Never readable by another origin (same-origin storage only).
- The UI shows a warning that the key transits the API server, because that is
  true and hiding it would be dishonest.

## Response shapes

`POST /api/v1/llm/verify`:

```json
{ "ok": true, "provider": "https://api.openai.com/v1", "model": "gpt-4o-mini",
  "checked": "models", "models": ["gpt-4o-mini", "gpt-4o"] }
```

Errors:

| Status | When |
| --- | --- |
| `400` | malformed header, base URL not allowed, provider rejected the key (401/403) |
| `403` | `LLM_BYOK_ENABLED=false` |
| `429` | provider returned 429, or the verify bucket is exhausted |
| `502` | provider unreachable / timeout |

No error body ever contains the key, its prefix, or its length.
