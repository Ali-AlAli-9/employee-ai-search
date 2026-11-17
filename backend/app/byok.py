"""Request-scoped LLM credentials (bring-your-own-key).

A visitor may send their own OpenAI-compatible credential in a header. It is
validated, held in a ``ContextVar`` for the duration of one pipeline run, and
then dropped. Nothing here writes to disk, a database, a trace or a log line.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, NoReturn
from urllib.parse import urlsplit

import httpx

from .config import settings

MAX_KEY_LENGTH = 200
MAX_BYOK_TIMEOUT = 30.0
VERIFY_TIMEOUT = 10.0

# Models are ids, never paths: this keeps a model name out of the request URL.
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/@+-]{1,120}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class LLMSettings:
    """One resolved LLM configuration for one request."""

    api_key: str
    model: str
    base_url: str
    timeout: float
    max_tokens: int
    source: str = "server"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


class ProviderRejected(ValueError):
    """The provider answered 401/403 for the supplied credential."""


class ProviderRateLimited(Exception):
    """The provider answered 429; the caller should say "quota", not "bad key"."""


class ProviderUnavailable(Exception):
    """The provider could not be reached or timed out."""


def normalise_base_url(raw: str) -> str:
    value = (raw or "").strip().rstrip("/")
    if not value:
        raise ValueError("Base URL is empty")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Base URL must be an http(s) URL")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError("Base URL must not contain credentials, a query or a fragment")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def allowed_base_urls() -> tuple[str, ...]:
    return tuple(normalise_base_url(url) for url in settings.llm_allowed_base_urls)


def validate_user_llm(
    api_key: str | None,
    model: str | None = None,
    base_url: str | None = None,
) -> LLMSettings:
    """Turn three headers into a validated, request-scoped configuration.

    Raises ``ValueError`` with a message that is safe to show to the user (it
    never includes the key itself).
    """
    key = (api_key or "").strip()
    if not key:
        raise ValueError("X-LLM-API-Key is empty")
    if len(key) > MAX_KEY_LENGTH:
        raise ValueError(f"The supplied key is longer than {MAX_KEY_LENGTH} characters")
    if _CONTROL_RE.search(key) or any(char.isspace() for char in key):
        raise ValueError("The supplied key contains whitespace or control characters")

    resolved_model = (model or settings.llm_model).strip()
    if not _MODEL_RE.match(resolved_model):
        raise ValueError("The supplied model name contains unsupported characters")

    allowed = allowed_base_urls()
    resolved_base = normalise_base_url(base_url or settings.llm_base_url)
    if resolved_base not in allowed:
        raise ValueError(
            "Base URL not allowed. Allowed providers: " + ", ".join(allowed)
        )

    return LLMSettings(
        api_key=key,
        model=resolved_model,
        base_url=resolved_base,
        timeout=min(settings.llm_timeout, MAX_BYOK_TIMEOUT),
        max_tokens=settings.llm_max_tokens,
        source="user",
    )


_current: ContextVar[LLMSettings | None] = ContextVar("llm_settings", default=None)


def resolve_llm() -> LLMSettings:
    """The configuration for the current request (user override or server key)."""
    override = _current.get()
    if override is not None:
        return override
    return LLMSettings(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=normalise_base_url(settings.llm_base_url),
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
        source="server",
    )


def no_llm() -> LLMSettings:
    """An explicit "no model" configuration.

    Passing this as the request override keeps the pipeline on its deterministic
    heuristic path. It is how a non-admin request avoids spending the
    deployment's key when BYOK is switched off.
    """
    return LLMSettings(
        api_key="",
        model=settings.llm_model,
        base_url=normalise_base_url(settings.llm_base_url),
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
        source="none",
    )


@contextmanager
def using_llm(config: LLMSettings | None) -> Iterator[None]:
    if config is None:
        yield
        return
    token = _current.set(config)
    try:
        yield
    finally:
        _current.reset(token)


def _authorisation(config: LLMSettings) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.api_key}"}


def _raise_for_provider_status(status_code: int) -> NoReturn:
    if status_code in {401, 403}:
        raise ProviderRejected("The provider rejected this key")
    if status_code == 429:
        raise ProviderRateLimited("The provider reports no quota left for this key")
    # Deliberately not echoing the response body: it can contain request ids
    # that a provider correlates with the credential.
    raise ValueError(f"The provider returned HTTP {status_code}")


def verify_key(config: LLMSettings) -> dict[str, Any]:
    """Check a credential with its provider without spending real tokens."""
    headers = _authorisation(config)
    try:
        response = httpx.get(
            f"{config.base_url}/models", headers=headers, timeout=VERIFY_TIMEOUT
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailable("Could not reach the provider") from exc

    if response.status_code == 200:
        try:
            body = response.json()
            models = [
                str(item.get("id"))
                for item in body.get("data", [])
                if isinstance(item, dict) and item.get("id")
            ]
        except (ValueError, AttributeError):
            models = []
        return {
            "ok": True,
            "provider": config.base_url,
            "model": config.model,
            "checked": "models",
            "models": models[:20],
        }
    if response.status_code not in {404, 405}:
        _raise_for_provider_status(response.status_code)

    # Some gateways do not expose /models. A one-token completion is the
    # cheapest honest check; it costs a fraction of a cent of the user's quota.
    try:
        response = httpx.post(
            f"{config.base_url}/chat/completions",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "model": config.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=min(config.timeout, 15.0),
        )
    except httpx.HTTPError as exc:
        raise ProviderUnavailable("Could not reach the provider") from exc
    if response.status_code == 200:
        return {
            "ok": True,
            "provider": config.base_url,
            "model": config.model,
            "checked": "completion",
            "models": [],
        }
    _raise_for_provider_status(response.status_code)
