"""HTTP API for the Employee AI Search Platform."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Iterator

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse

from . import db, identity
from .agents import PipelineResult, orchestrator
from .byok import (
    LLMSettings,
    ProviderRateLimited,
    ProviderRejected,
    ProviderUnavailable,
    no_llm,
    validate_user_llm,
    verify_key,
)
from .config import settings
from .embeddings import get_embedder
from .ingestion import ALLOWED_EXTENSIONS, ingest_document
from .ratelimit import rate_limit
from .schemas import ChatRequest, SearchRequest
from .search import hybrid_search
from .security import Principal, require_role
from .store import get_store

logger = logging.getLogger(__name__)

router = APIRouter()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Also mirrored by the web client (`LLM_KEY_REQUIRED_DETAIL` in lib/api.ts).
SERVER_KEY_ADMIN_ONLY = (
    "The server API key is reserved for administrators. "
    "Add your own provider key to continue."
)

# Internal failures are logged in full but never returned verbatim: exception
# text can carry connection strings, file paths or provider request ids.
HEALTH_FAILURE_DETAIL = "A dependency check failed"
READINESS_FAILURE_DETAIL = "Service is not ready"
CHAT_FAILURE_DETAIL = "The assistant could not finish the answer. Please try again."


def _key_required() -> HTTPException:
    """The single 402 contract shared by strict mode and server-key mode."""
    return HTTPException(
        status_code=402,
        detail=SERVER_KEY_ADMIN_ONLY,
        headers={"X-LLM-Key-Required": "1"},
    )


def _workspace_id(principal: Principal) -> str | None:
    """Workspace that scopes this request's documents, history and retrieval.

    ``Principal.workspace_id`` is authoritative. The fallback keeps older
    callers (and tests using hand-built principals) on the default workspace
    until the auth layer has finished populating the field.
    """
    return getattr(principal, "workspace_id", None) or getattr(
        settings, "default_workspace_id", "ws_default"
    )


def _validated_document_ids(
    document_ids: list[str] | None, workspace_id: str | None
) -> list[str] | None:
    """Reject document ids that are unknown or not indexed in this workspace.

    These ids come straight from the request body; retrieval alone would simply
    ignore them, which hides cross-workspace probing inside a successful answer.
    """
    if not document_ids:
        return document_ids
    allowed = set(db.completed_document_ids(document_ids, workspace_id=workspace_id))
    unknown = next((doc_id for doc_id in document_ids if doc_id not in allowed), None)
    if unknown is not None:
        raise HTTPException(status_code=404, detail=f"Document not found: {unknown}")
    return document_ids


def _request_llm(
    principal: Principal, provided: LLMSettings | None
) -> LLMSettings | None:
    """Decide whose credential this request may use.

    A visitor-supplied key always wins. The deployment's key is an admin
    privilege: everyone else must bring a key (when BYOK is enabled), otherwise
    the pipeline answers with the free deterministic heuristics. An operator can
    opt into ``REQUIRE_CHAT_BYOK`` to disable that free path for non-admins.
    """
    if provided is not None or principal.role == "admin":
        return provided
    if settings.require_chat_byok:
        raise _key_required()
    if not settings.llm_enabled:
        return None
    if settings.llm_byok_enabled:
        raise _key_required()
    return no_llm()


def _persist(
    query_id: str,
    text: str,
    query_type: str,
    user_id: str,
    results_count: int,
    latency_ms: int,
    result: PipelineResult | None = None,
    citations: list[dict[str, Any]] | None = None,
    workspace_id: str | None = None,
) -> None:
    db.record_query(
        query_id,
        text,
        query_type,
        user_id,
        results_count,
        latency_ms,
        trace_id=query_id,
        workspace_id=workspace_id,
    )
    if result is not None:
        db.record_trace(
            query_id,
            {
                "answer": result.answer,
                "citations": result.citations,
                "confidence": result.confidence,
                "sub_queries": result.sub_queries,
                "strategy": result.strategy,
                "trace": result.trace,
            },
        )
    elif citations is not None:
        db.record_trace(
            query_id,
            {"answer": "", "citations": citations, "confidence": 0.0},
        )


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@router.get("/health")
def health() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        with db.get_conn() as conn:
            conn.execute("SELECT 1")
        checks["database"] = {"status": "healthy"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("health check failed for database: %s", exc)
        checks["database"] = {"status": "unhealthy", "detail": HEALTH_FAILURE_DETAIL}

    try:
        checks["vector_store"] = {"status": "healthy", "points": get_store().count()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("health check failed for vector store: %s", exc)
        checks["vector_store"] = {
            "status": "unhealthy",
            "detail": HEALTH_FAILURE_DETAIL,
        }

    embedder = get_embedder()
    checks["embedding_model"] = {
        "status": "loaded",
        # Report what the process actually uses: the API backend may have fallen
        # back to hashing, and an API model can have a different width.
        "backend": getattr(embedder, "backend", settings.embedding_backend),
        "model": getattr(embedder, "model", settings.embedding_model),
        "dimension": getattr(embedder, "dimension", settings.embedding_dimension),
        # Safe booleans: tell us whether the env var reached the process without
        # exposing either token itself.
        "hf_api_key_configured": bool(settings.hf_api_key),
        "gemini_api_key_configured": bool(settings.gemini_api_key),
    }
    checks["llm_api"] = {
        "status": "reachable" if settings.llm_enabled else "disabled",
        "provider": settings.llm_base_url if settings.llm_enabled else "heuristic",
        # Whether a visitor may bring their own key; the UI uses this to hide
        # the panel instead of failing at request time.
        "byok": settings.llm_byok_enabled,
        # Opt-in strict gate: keyless non-admin chat is refused before the
        # pipeline runs. Secret-free so the public health probe can expose it.
        "require_chat_byok": settings.require_chat_byok,
        # The deployment key never answers for a non-admin. The UI uses this to
        # show "key required" instead of promising server-backed answers.
        "server_key_admin_only": True,
    }
    # Public, secret-free flags the UI needs before rendering the auth panel.
    checks["auth"] = identity.health()

    healthy_states = {"healthy", "loaded", "reachable", "disabled"}
    status = "healthy" if all(c.get("status") in healthy_states for c in checks.values()) else "degraded"
    return {
        "status": status,
        "version": settings.version,
        "timestamp": db.now_iso(),
        "storage": {"engine": db.dialect()},
        "checks": checks,
    }


@router.get("/health/ready")
def readiness() -> dict[str, Any]:
    try:
        with db.get_conn() as conn:
            conn.execute("SELECT 1")
        get_store().count()
        return {"ready": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness check failed: %s", exc)
        raise HTTPException(status_code=503, detail=READINESS_FAILURE_DETAIL) from exc


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
def _queue_ingestion(
    background: BackgroundTasks,
    document_id: str,
    filename: str,
    content: bytes,
    workspace_id: str | None,
) -> None:
    """Schedule ingestion with the caller's workspace scope.

    The signature check keeps legacy ingest callables (for example test doubles
    from before workspaces existed) working while the real task always receives
    the workspace id.
    """
    task = ingest_document
    try:
        parameters = inspect.signature(task).parameters
        accepts_scope = "workspace_id" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
    except (TypeError, ValueError):
        accepts_scope = True
    if accepts_scope:
        background.add_task(
            task, document_id, filename, content, workspace_id=workspace_id
        )
    else:
        background.add_task(task, document_id, filename, content)


@router.post("/documents/upload", status_code=202)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    replace: bool = Query(
        default=False,
        description="Replace an existing document with the same content hash.",
    ),
    principal: Principal = Depends(require_role("viewer")),
    _rate: None = Depends(rate_limit("upload")),
) -> dict[str, Any]:
    workspace_id = _workspace_id(principal)
    filename = file.filename or "upload.bin"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.max_upload_mb}MB limit",
        )

    content_hash = hashlib.sha256(content).hexdigest()
    existing = db.find_document_by_hash(content_hash, workspace_id=workspace_id)
    if existing is not None and not replace:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "A document with identical content already exists. "
                    "Pass replace=true to replace it."
                ),
                "document_id": existing["id"],
                "filename": existing["filename"],
                "status": existing["status"],
            },
        )
    if existing is not None:
        # Replacing deletes the previous chunks and vectors, so it is a delete
        # with extra steps: only the uploader or an admin may do it.
        if principal.role != "admin" and existing.get("uploaded_by") != principal.id:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Only an administrator can replace another account's document."
                ),
            )
        logger.info(
            "replacing duplicate document old=%s filename=%s", existing["id"], filename
        )
        _remove_document(existing["id"], workspace_id=workspace_id)

    try:
        document_id = db.create_document(
            filename=filename,
            stored_filename=document_id_safe_name(filename),
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
            uploaded_by=principal.id,
            content_hash=content_hash,
            workspace_id=workspace_id,
        )
    except db.IntegrityErrors as exc:
        # Two identical uploads raced past the check above; the partial unique
        # index caught the second one.
        duplicate = db.find_document_by_hash(content_hash, workspace_id=workspace_id)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A document with identical content already exists.",
                "document_id": duplicate["id"] if duplicate else "",
                "filename": duplicate["filename"] if duplicate else filename,
                "status": duplicate["status"] if duplicate else "pending",
            },
        ) from exc

    _queue_ingestion(background, document_id, filename, content, workspace_id)
    return {
        "document_id": document_id,
        "filename": filename,
        "status": "pending",
        "message": "Document uploaded successfully. Processing started.",
    }


def _remove_document(document_id: str, workspace_id: str | None = None) -> bool:
    """Delete a document everywhere: chunks, row and vectors.

    Every step is workspace-scoped. An admin in workspace A must not be able to
    delete a document in workspace B by guessing its id, so a document that is
    not visible in the caller's workspace is left completely untouched.
    """
    if db.get_document(document_id, workspace_id=workspace_id) is None:
        return False
    if not db.delete_document(document_id, workspace_id=workspace_id):
        return False
    db.delete_chunks_by_document(document_id, workspace_id=workspace_id)
    try:
        get_store().delete_document(document_id, workspace_id=workspace_id)
    except Exception as exc:  # noqa: BLE001 - vector cleanup is best effort
        logger.warning("vector cleanup failed document=%s: %s", document_id, exc)
    return True


def document_id_safe_name(filename: str) -> str:
    return "".join(c for c in filename if c.isalnum() or c in "._-") or "document"


@router.get("/documents")
def list_documents(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    content_type: str | None = None,
    principal: Principal = Depends(require_role("viewer")),
) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    items, total = db.list_documents(
        page=page,
        page_size=page_size,
        status=status,
        content_type=content_type,
        workspace_id=_workspace_id(principal),
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if page_size else 0,
    }


@router.get("/documents/{document_id}")
def get_document(
    document_id: str, principal: Principal = Depends(require_role("viewer"))
) -> dict[str, Any]:
    document = db.get_document(document_id, workspace_id=_workspace_id(principal))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: str, principal: Principal = Depends(require_role("admin"))
) -> None:
    workspace_id = _workspace_id(principal)
    document = db.get_document(document_id, workspace_id=workspace_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    _remove_document(document_id, workspace_id=workspace_id)


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
@router.post("/search")
def search(
    payload: SearchRequest,
    principal: Principal = Depends(require_role("viewer")),
    _rate: None = Depends(rate_limit("search")),
) -> dict[str, Any]:
    started = time.perf_counter()
    workspace_id = _workspace_id(principal)
    document_ids = _validated_document_ids(
        payload.filters.document_ids if payload.filters else None, workspace_id
    )
    results = hybrid_search(
        payload.query,
        top_k=payload.top_k,
        search_type=payload.search_type,
        document_ids=document_ids,
        rerank=payload.rerank,
        workspace_id=workspace_id,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    query_id = db.new_id()
    _persist(
        query_id,
        payload.query,
        "search",
        principal.id,
        len(results),
        latency_ms,
        citations=results,
        workspace_id=workspace_id,
    )
    return {
        "query": payload.query,
        "results": results,
        "total_found": len(results),
        "search_time_ms": latency_ms,
        "search_type": payload.search_type,
    }


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
def user_llm(
    x_llm_api_key: str | None = Header(default=None, alias="X-LLM-API-Key"),
    x_llm_model: str | None = Header(default=None, alias="X-LLM-Model"),
    x_llm_base_url: str | None = Header(default=None, alias="X-LLM-Base-URL"),
) -> LLMSettings | None:
    """Resolve an optional visitor-supplied credential for this request."""
    if not (x_llm_api_key or "").strip():
        return None
    if not settings.llm_byok_enabled:
        raise HTTPException(
            status_code=403, detail="Bring-your-own-key is disabled on this deployment"
        )
    try:
        return validate_user_llm(x_llm_api_key, x_llm_model, x_llm_base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/llm/verify")
def verify_llm(
    principal: Principal = Depends(require_role("viewer")),
    _rate: None = Depends(rate_limit("llm_verify")),
    llm_config: LLMSettings | None = Depends(user_llm),
) -> dict[str, Any]:
    """Check a visitor's key with its provider; never echoes the credential."""
    if llm_config is None:
        raise HTTPException(status_code=400, detail="X-LLM-API-Key is required")
    try:
        return verify_key(llm_config)
    except ProviderRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": "30"},
        ) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chat")
def chat(
    payload: ChatRequest,
    principal: Principal = Depends(require_role("viewer")),
    _rate: None = Depends(rate_limit("chat")),
    llm_config: LLMSettings | None = Depends(user_llm),
):
    llm_config = _request_llm(principal, llm_config)
    workspace_id = _workspace_id(principal)
    document_ids = _validated_document_ids(payload.document_ids, workspace_id)
    history = [m.model_dump() for m in payload.conversation_history]
    query_id = db.new_id()
    started = time.perf_counter()

    def run_pipeline() -> PipelineResult:
        return orchestrator.run(
            payload.message,
            history=history,
            language=payload.language,
            top_k=payload.top_k,
            search_type=payload.search_type,
            document_ids=document_ids,
            llm_config=llm_config,
            workspace_id=workspace_id,
        )

    if payload.stream:

        def event_stream() -> Iterator[str]:
            try:
                result = run_pipeline()
                buffer: list[str] = []
                for word in result.answer.split(" "):
                    buffer.append(word)
                    if len(buffer) >= 3:
                        yield _sse("token", {"token": " ".join(buffer) + " "})
                        buffer = []
                if buffer:
                    yield _sse("token", {"token": " ".join(buffer)})

                for citation in result.citations:
                    yield _sse("citation", citation)

                latency_ms = int((time.perf_counter() - started) * 1000)
                _persist(
                    query_id,
                    payload.message,
                    "chat",
                    principal.id,
                    len(result.chunks),
                    latency_ms,
                    result=result,
                    workspace_id=workspace_id,
                )
                yield _sse(
                    "done",
                    {
                        "answer": result.answer,
                        "confidence": result.confidence,
                        "query_id": query_id,
                        "latency_ms": latency_ms,
                        "llm_source": result.llm_source,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - report through SSE
                logger.exception("chat pipeline failed query=%s", query_id)
                yield _sse(
                    "error", {"error": CHAT_FAILURE_DETAIL, "query_id": query_id}
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    result = run_pipeline()
    latency_ms = int((time.perf_counter() - started) * 1000)
    _persist(
        query_id,
        payload.message,
        "chat",
        principal.id,
        len(result.chunks),
        latency_ms,
        result=result,
        workspace_id=workspace_id,
    )
    return {
        "answer": result.answer,
        "citations": result.citations,
        "confidence": result.confidence,
        "query_id": query_id,
        "latency_ms": latency_ms,
        "llm_source": result.llm_source,
        "sub_queries": result.sub_queries,
        "strategy": result.strategy,
        "trace": result.trace,
    }


@router.get("/chat/history")
def chat_history(
    page: int = 1,
    page_size: int = 20,
    principal: Principal = Depends(require_role("viewer")),
) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(page_size, 50))
    items, total = db.list_chat_history(
        principal.id,
        page=page,
        page_size=page_size,
        workspace_id=_workspace_id(principal),
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if page_size else 0,
    }
