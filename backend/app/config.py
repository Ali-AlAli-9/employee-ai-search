"""Application configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """Load ``KEY=VALUE`` pairs from the nearest ``.env`` file.

    Walks up from the working directory so both ``backend/`` and the repository
    root work. Values already present in the real environment always win, so a
    shell export or a Render dashboard variable overrides the file. Kept
    dependency-free (no python-dotenv) so the offline demo stays one install.
    """
    for parent in (Path.cwd(), *Path.cwd().parents):
        candidate = parent / ".env"
        if not candidate.is_file():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        return


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)) or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)) or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return _env(name, "true" if default else "false").lower() in {"1", "true", "yes", "on"}


# One source of truth for the API/OSS embedding models we support. The inference
# API returns these exact widths; a mismatch silently breaks the vector store.
# Only models actually served by the hf-inference provider belong here: the Hub
# list at /api/models?inference_provider=hf-inference is authoritative.
DEFAULT_EMBEDDING_MODEL = "ibm-granite/granite-embedding-97m-multilingual-r2"
# Free-tier Gemini embeddings (spec 006). Kept separate from the HF catalogue
# because the two providers use incompatible model ids and task formats.
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
GEMINI_EMBEDDING_MODELS: dict[str, int] = {GEMINI_EMBEDDING_MODEL: 768}
GEMINI_EMBEDDING_DIMENSION = 768
# Offline hashing embeddings are the hosted default: no model download, no
# second service, no quota, and the API stays tiny on the free plan. Lexical
# BM25 carries retrieval; the LLM decides how to answer from the cited chunks.
HASHING_MODEL = "hashing"
HASHING_DIMENSION = 384
MODEL_DIMENSIONS: dict[str, int] = {
    DEFAULT_EMBEDDING_MODEL: 384,
    GEMINI_EMBEDDING_MODEL: GEMINI_EMBEDDING_DIMENSION,
    "ibm-granite/granite-embedding-311m-multilingual-r2": 768,
    "BAAI/bge-m3": 1024,
    "intfloat/multilingual-e5-large": 1024,
    "intfloat/multilingual-e5-base": 768,
    "intfloat/multilingual-e5-small": 384,
    "intfloat/multilingual-e5-large-instruct": 1024,
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
}

# E5 models are trained with asymmetric prefixes: without them, Arabic queries
# match noticeably worse than the same query passed as a passage.
_E5_MODELS = {
    "intfloat/multilingual-e5-large",
    "intfloat/multilingual-e5-base",
    "intfloat/multilingual-e5-small",
}
QUERY_PREFIXES: dict[str, str] = {model: "query: " for model in _E5_MODELS}
PASSAGE_PREFIXES: dict[str, str] = {model: "passage: " for model in _E5_MODELS}

# Subset of MODEL_DIMENSIONS actually served by the hf-inference provider.
# Verified against https://huggingface.co/api/models?inference_provider=hf-inference
# The API answers 400 "Model not supported by provider hf-inference" for any
# other id, so do not send those to the router.
HF_INFERENCE_MODELS: set[str] = {
    "ibm-granite/granite-embedding-97m-multilingual-r2",
    "ibm-granite/granite-embedding-311m-multilingual-r2",
    "intfloat/multilingual-e5-large",
    "intfloat/multilingual-e5-large-instruct",
    "BAAI/bge-small-en-v1.5",
    "BAAI/bge-base-en-v1.5",
    "BAAI/bge-large-en-v1.5",
}


def _embedding_model() -> str:
    """Default the model to the selected backend's known-good value."""
    model = _env("EMBEDDING_MODEL", "")
    backend = _env("EMBEDDING_BACKEND", "hashing").lower()
    if backend == "hashing":
        # Ignore a leftover model id from an older two-service deployment.
        return HASHING_MODEL
    if model:
        return model
    if backend == "gemini":
        return GEMINI_EMBEDDING_MODEL
    return DEFAULT_EMBEDDING_MODEL


def _embedding_dimension() -> int:
    """Explicit override wins; otherwise derive the width from the backend."""
    raw = _env("EMBEDDING_DIMENSION")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    backend = _env("EMBEDDING_BACKEND", "hashing").lower()
    model = _env("EMBEDDING_MODEL", "")
    if backend == "hashing":
        return HASHING_DIMENSION
    if backend == "gemini":
        # An old hf-api model id must not drag its 384 width into Gemini.
        return GEMINI_EMBEDDING_MODELS.get(model, GEMINI_EMBEDDING_DIMENSION)
    return MODEL_DIMENSIONS.get(model or DEFAULT_EMBEDDING_MODEL, HASHING_DIMENSION)


# Convenient for the offline demo and the test suite; a production deployment
# that forgets to replace them must not silently hand out admin access.
_DEV_API_KEYS = {
    "ADMIN_API_KEY": ("dev-admin-key", "admin"),
    "USER_API_KEY": ("dev-user-key", "user"),
    "VIEWER_API_KEY": ("dev-viewer-key", "viewer"),
}


def _api_keys() -> dict[str, str]:
    """Map API key -> role. Roles are ranked: viewer < user < admin.

    Defaults only apply outside production. In production a missing or unchanged
    development key is skipped (with a warning) rather than accepted — failing
    closed here is safer than crashing the whole service over one bad variable.
    """
    production = _env("ENVIRONMENT").lower() == "production"
    keys: dict[str, str] = {}
    for name, (default, role) in _DEV_API_KEYS.items():
        value = _env(name, "" if production else default)
        if not value:
            continue
        if production and value == default:
            logger.warning("%s is still the development default; ignoring it in production", name)
            continue
        keys[value] = role
    return keys


@dataclass(frozen=True)
class Settings:
    app_name: str = "Employee AI Search Platform"
    version: str = "1.0.0"
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO").upper())

    # Storage. SQLite is used by default so the app runs with zero external services.
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", ""))

    # Workspaces. The default rows are created (and legacy rows backfilled) by
    # db.init_db(); keeping the ids here lets every deployment share one
    # well-known home for pre-isolation data and the bootstrap admin.
    default_workspace_id: str = field(
        default_factory=lambda: _env("DEFAULT_WORKSPACE_ID", "ws_default")
    )
    default_workspace_name: str = field(
        default_factory=lambda: _env("DEFAULT_WORKSPACE_NAME", "Default workspace")
    )

    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip() for origin in _env("CORS_ORIGINS", "*").split(",") if origin.strip()
        )
    )

    api_keys: dict[str, str] = field(default_factory=_api_keys)

    # Embeddings
    embedding_backend: str = field(
        default_factory=lambda: _env("EMBEDDING_BACKEND", "hashing").lower()
    )
    embedding_model: str = field(default_factory=_embedding_model)
    embedding_dimension: int = field(default_factory=_embedding_dimension)
    # Hugging Face Inference API (for EMBEDDING_BACKEND=hf-api)
    hf_api_key: str = field(default_factory=lambda: _env("HF_API_KEY", ""))
    # Gemini Developer API (for EMBEDDING_BACKEND=gemini). Server-only secret.
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY", ""))
    # Ingestion embeds records in batches so no single vector array holds a
    # whole document. Hashing is instant; API-backed backends stay bounded.
    embedding_batch_size: int = field(
        default_factory=lambda: _env_int("EMBEDDING_BATCH_SIZE", 64)
    )

    # Chunking
    chunk_size_tokens: int = field(default_factory=lambda: _env_int("CHUNK_SIZE", 256))
    chunk_overlap_tokens: int = field(default_factory=lambda: _env_int("CHUNK_OVERLAP", 40))

    # Search
    hybrid_alpha: float = field(default_factory=lambda: _env_float("HYBRID_ALPHA", 0.5))
    default_top_k: int = field(default_factory=lambda: _env_int("DEFAULT_TOP_K", 10))
    max_top_k: int = field(default_factory=lambda: _env_int("MAX_TOP_K", 50))
    # Per-document retrieval gives every indexed document its own top-K slot
    # before the hits are merged, so a long dominant file cannot crowd out a
    # short but relevant one. The merged answer still respects `top_k`.
    per_document_top_k: int = field(
        default_factory=lambda: _env_int("PER_DOCUMENT_TOP_K", 5)
    )
    # Lexical (hashing) mode tunables. Measured on eval/thesis-questions.json:
    # the offline hashing vector is a bag of content terms, so it adds noise to
    # ranking - BM25 leads and the vector only widens the candidate set. With a
    # trained embedder (EMBEDDING_BACKEND=sentence-transformers) HYBRID_ALPHA is
    # used directly and the vector carries half the score.
    hashing_vector_weight: float = field(
        default_factory=lambda: _env_float("HASHING_VECTOR_WEIGHT", 0.0)
    )
    hashing_min_coverage: float = field(
        default_factory=lambda: _env_float("HASHING_MIN_COVERAGE", 0.35)
    )
    rerank_coverage_weight: float = field(
        default_factory=lambda: _env_float("RERANK_COVERAGE_WEIGHT", 0.5)
    )
    # A question that *is* a section title retrieves the heading line but not the
    # paragraphs under it; pull this many following chunks so the body is answerable.
    section_expand: int = field(
        default_factory=lambda: _env_int("RETRIEVAL_SECTION_EXPAND", 3)
    )

    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 50))
    # Safety valve for pathological files (a binary renamed .txt, thousands of
    # pages). The original 6000 cap protected a 512 MB ONNX worker that died
    # mid-upload; offline hashing embeds 20k chunks (~30 MB of vectors) with no
    # model in memory, so a generous cap lets large real documents through.
    max_chunks_per_document: int = field(
        default_factory=lambda: _env_int("MAX_CHUNKS_PER_DOCUMENT", 20000)
    )
    # Drop table-of-contents chunks at ingestion: dotted-leader rows are near-exact
    # matches for section-title questions and otherwise outrank the real body.
    toc_filter: bool = field(default_factory=lambda: _env_bool("TOC_FILTER", True))
    # Repair Arabic PDFs that pypdf extracts in visual (mirrored) order.
    pdf_visual_order_repair: bool = field(
        default_factory=lambda: _env_bool("PDF_VISUAL_ORDER_REPAIR", True)
    )

    # Optional Qdrant vector database. Falls back to local file store when empty.
    qdrant_url: str = field(default_factory=lambda: _env("QDRANT_URL", ""))
    qdrant_api_key: str = field(default_factory=lambda: _env("QDRANT_API_KEY", ""))
    qdrant_collection: str = field(
        default_factory=lambda: _env("QDRANT_COLLECTION", "documents_chunks")
    )

    # Query cache. Keyed by corpus version, so any upload/delete invalidates it.
    search_cache_size: int = field(
        default_factory=lambda: _env_int("SEARCH_CACHE_SIZE", 128)
    )
    search_cache_ttl_seconds: float = field(
        default_factory=lambda: _env_float("SEARCH_CACHE_TTL_SECONDS", 300.0)
    )

    # Per-IP rate limits (requests per minute). In-memory token buckets: the
    # free instance is a single process, so no external store is needed.
    rate_limit_enabled: bool = field(
        default_factory=lambda: _env_bool("RATE_LIMIT_ENABLED", True)
    )
    # Render appends the real visitor as the last X-Forwarded-For hop. Trusting
    # it stops a caller from spoofing the first hop to obtain a fresh bucket;
    # set this to 0 only when the app is exposed directly without a proxy.
    trust_proxy_headers: bool = field(
        default_factory=lambda: _env_bool("TRUST_PROXY_HEADERS", True)
    )
    rate_limit_search_per_minute: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_SEARCH_PER_MINUTE", 60)
    )
    rate_limit_chat_per_minute: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_CHAT_PER_MINUTE", 20)
    )
    rate_limit_upload_per_minute: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_UPLOAD_PER_MINUTE", 10)
    )
    # Verifying a visitor's own key calls the provider, so it gets its own bucket.
    rate_limit_llm_verify_per_minute: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_LLM_VERIFY_PER_MINUTE", 10)
    )
    # Login/register/demo share one bucket so password guessing cannot spray
    # across the three routes for free. Account lockout adds a second axis for
    # attackers that rotate source addresses. Unknown emails are counted too,
    # so the lock cannot reveal whether an account exists.
    rate_limit_auth_per_minute: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_AUTH_PER_MINUTE", 10)
    )
    login_lock_max_failures: int = field(
        default_factory=lambda: _env_int("LOGIN_LOCK_MAX_FAILURES", 5)
    )
    login_lock_minutes: int = field(
        default_factory=lambda: _env_int("LOGIN_LOCK_MINUTES", 15)
    )
    # The user-administration API is authenticated, so it only needs a guard
    # against a runaway script, not against anonymous abuse.
    rate_limit_admin_per_minute: int = field(
        default_factory=lambda: _env_int("RATE_LIMIT_ADMIN_PER_MINUTE", 120)
    )

    # Accounts and sessions. Cookies are first-party (same-origin proxy) and
    # HttpOnly; the CSRF token is the only readable cookie.
    session_ttl_hours: int = field(
        default_factory=lambda: _env_int("SESSION_TTL_HOURS", 168)
    )
    session_secure: bool = field(
        default_factory=lambda: _env_bool(
            "SESSION_SECURE", _env("ENVIRONMENT", "development").lower() == "production"
        )
    )
    cookie_domain: str = field(default_factory=lambda: _env("COOKIE_DOMAIN", ""))
    # Empty means registration is public: anyone can create an account. Set a
    # shared code to switch to invite-only; no email is ever sent.
    invite_code: str = field(default_factory=lambda: _env("INVITE_CODE", ""))
    demo_login_enabled: bool = field(
        default_factory=lambda: _env_bool("DEMO_LOGIN_ENABLED", True)
    )
    password_min_length: int = field(
        default_factory=lambda: _env_int("PASSWORD_MIN_LENGTH", 8)
    )
    # Env-as-source-of-truth admin: created (or repaired) at every startup.
    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL", ""))
    admin_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD", ""))

    # ----------------------------------------------------------------------- #
    # Identity provider. Supabase Auth (GoTrue) is the deployment provider;
    # "local" keeps the spec-004 scrypt/session implementation for offline runs
    # and the network-free test suite.
    # ----------------------------------------------------------------------- #
    auth_provider: str = field(
        default_factory=lambda: (
            _env("AUTH_PROVIDER", "").lower()
            or ("supabase" if _env("SUPABASE_URL", "") else "local")
        )
    )
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL", "").rstrip("/"))
    supabase_anon_key: str = field(default_factory=lambda: _env("SUPABASE_ANON_KEY", ""))
    # Server-only. Never returned, logged or shipped to the browser.
    supabase_service_role_key: str = field(
        default_factory=lambda: _env("SUPABASE_SERVICE_ROLE_KEY", "")
    )
    supabase_jwt_secret: str = field(default_factory=lambda: _env("SUPABASE_JWT_SECRET", ""))
    supabase_jwks_url: str = field(default_factory=lambda: _env("SUPABASE_JWKS_URL", ""))
    supabase_timeout_seconds: float = field(
        default_factory=lambda: _env_float("SUPABASE_TIMEOUT_SECONDS", 15.0)
    )
    # Admin sync pulls this many 1000-user pages at most, so a runaway loop
    # cannot spend the whole request budget on a free instance.
    supabase_sync_max_pages: int = field(
        default_factory=lambda: _env_int("SUPABASE_SYNC_MAX_PAGES", 10)
    )
    # Where the recovery email lands. Supabase falls back to the project Site
    # URL when empty; set it to https://your-web-host/auth/reset.
    password_reset_redirect_to: str = field(
        default_factory=lambda: _env("PASSWORD_RESET_REDIRECT_TO", "")
    )

    # Optional OpenAI-compatible LLM. Falls back to deterministic heuristics.
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "https://api.openai.com/v1")
    )
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gpt-4o-mini"))
    llm_timeout: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT", 45.0))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 512))

    # Bring-your-own-key: a visitor may send their provider credential in a
    # request header. It is used for that request only and never stored. The
    # base URL is restricted to an allow-list so the header cannot be pointed at
    # an arbitrary host (SSRF / credential exfiltration).
    llm_byok_enabled: bool = field(default_factory=lambda: _env_bool("LLM_BYOK_ENABLED", True))
    # Operator opt-in: require a visitor key for every non-admin chat. The
    # default keeps free/offline deterministic answers and demo guests working.
    require_chat_byok: bool = field(
        default_factory=lambda: _env_bool("REQUIRE_CHAT_BYOK", False)
    )
    llm_allowed_base_urls: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            part.strip()
            for part in _env(
                "LLM_ALLOWED_BASE_URLS",
                "https://api.openai.com/v1,https://openrouter.ai/api/v1,"
                "https://api.groq.com/openai/v1",
            ).split(",")
            if part.strip()
        )
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def vectors_path(self) -> Path:
        return self.data_dir / "vectors.npz"

    @property
    def legacy_vectors_path(self) -> Path:
        return self.data_dir / "vectors.json"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def supabase_enabled(self) -> bool:
        """True when Supabase Auth is the selected, usable provider."""
        return self.auth_provider == "supabase" and bool(self.supabase_url)

    @property
    def supabase_admin_enabled(self) -> bool:
        """Admin operations need the service-role key; login does not."""
        return self.supabase_enabled and bool(self.supabase_service_role_key)

    @property
    def jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if not self.supabase_url:
            return ""
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def session_ttl_seconds(self) -> int:
        return max(1, self.session_ttl_hours) * 3600

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
