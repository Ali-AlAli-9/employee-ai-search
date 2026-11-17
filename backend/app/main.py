"""FastAPI application entry point."""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, identity
from .api import readiness, router
from .auth_api import router as auth_router
from .config import settings

# Every log record carries the id of the request that produced it. A contextvar
# works for both async and threadpool endpoints, and a global record factory
# means it does not matter which handler (root, uvicorn, pytest) emits the line.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_original_record_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs):
    record = _original_record_factory(*args, **kwargs)
    record.request_id = _request_id.get()
    return record


logging.setLogRecordFactory(_record_factory)

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
)
logger = logging.getLogger(__name__)

# Initialise eagerly so the schema exists even when the app is imported by a test
# client that does not run lifespan events.
settings.ensure_dirs()
db.init_db()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    db.init_db()
    # Env-as-source-of-truth admin; idempotent and never logs the password.
    identity.bootstrap_admin()
    logger.info(
        "startup environment=%s storage=%s data_dir=%s embeddings=%s llm=%s auth=%s",
        settings.environment,
        db.dialect(),
        settings.data_dir,
        settings.embedding_backend,
        "enabled" if settings.llm_enabled else "heuristic",
        identity.provider_name(),
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
    description=(
        "Search company documents and get answers with citations. "
        "Runs locally with SQLite and a file-backed vector store, or with Postgres and Qdrant when configured."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    # Wildcard origins cannot be combined with credentials. Cookie auth is
    # same-origin through the Next.js proxy; direct browser -> API mode needs an
    # explicit CORS_ORIGINS list.
    allow_credentials="*" not in settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "")
    request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    token = _request_id.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request failed method=%s path=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            (time.perf_counter() - started) * 1000,
        )
        raise
    else:
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request method=%s path=%s status=%d duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
    finally:
        _request_id.reset(token)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")


@app.api_route("/", methods=["GET", "HEAD"])
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "docs": "/docs",
        "health": "/api/v1/health",
    }


# Render (and most uptime monitors) probe /health by default. Answer it with the
# real readiness check instead of a 404 so the logs stop filling with noise.
@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
def health_alias() -> dict[str, bool]:
    return readiness()
