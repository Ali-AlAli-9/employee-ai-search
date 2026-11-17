"""Read-only consistency checks and opt-in repairs for the document index.

Three stores hold what the app knows: the `documents` row, its `chunks` rows and
the vectors in the local/Qdrant store. Nothing guarantees they agree. When they
disagree, retrieval quietly answers badly, so the check treats an unreadable
store as a failure instead of a clean bill of health.

Repairs are deliberately inert unless ``apply=True``. Even then, only the
classes of damage the caller explicitly requested are touched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .store import get_store

logger = logging.getLogger(__name__)

VECTOR_STORE_ERROR_DETAIL = "The vector store could not be read. Check the deployment logs."
RECONCILE_STALE_DETAIL = (
    "Ingestion was interrupted before this document finished indexing. "
    "Delete and re-upload it to try again."
)


@dataclass
class ConsistencyReport:
    count_mismatches: list[dict[str, Any]] = field(default_factory=list)
    orphan_chunks: list[str] = field(default_factory=list)
    orphan_vectors: list[str] = field(default_factory=list)
    missing_vectors: list[str] = field(default_factory=list)
    stale_processing: list[dict[str, Any]] = field(default_factory=list)
    vector_store_error: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.vector_store_error is None
            and not self.count_mismatches
            and not self.orphan_chunks
            and not self.orphan_vectors
            and not self.missing_vectors
            and not self.stale_processing
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "count_mismatches": self.count_mismatches,
            "orphan_chunks": self.orphan_chunks,
            "orphan_vectors": self.orphan_vectors,
            "missing_vectors": self.missing_vectors,
            "stale_processing": self.stale_processing,
            "vector_store_error": self.vector_store_error,
        }


def _cutoff(stale_minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=max(0, stale_minutes))).isoformat()


def inspect(*, stale_minutes: int = 30, store: Any = None) -> ConsistencyReport:
    """Compare document rows, chunk rows and vector points without writing."""
    selected = store or get_store()
    documents = db.all_documents()
    document_ids = {str(row["id"]) for row in documents}
    chunk_counts = db.document_chunk_counts()
    chunk_refs = db.all_chunk_refs()

    report = ConsistencyReport()
    for row in documents:
        actual = chunk_counts.get(str(row["id"]), 0)
        declared = int(row.get("chunks_count") or 0)
        if declared != actual:
            report.count_mismatches.append(
                {
                    "id": str(row["id"]),
                    "filename": str(row.get("filename", "")),
                    "declared": declared,
                    "actual": actual,
                }
            )

    report.orphan_chunks = sorted(
        chunk_id for chunk_id, owner in chunk_refs.items() if owner not in document_ids
    )
    report.stale_processing = db.stale_documents("processing", _cutoff(stale_minutes))

    try:
        points = selected.all_points()
    except Exception:  # noqa: BLE001 - a failed check must be reported
        # The full exception goes to the server log, never to the command output:
        # it can contain local paths or provider text that is not safe to echo.
        logger.exception("vector store consistency check failed")
        report.vector_store_error = VECTOR_STORE_ERROR_DETAIL
        return report

    point_ids = {point_id for point_id, _ in points}
    report.orphan_vectors = sorted(point_id for point_id in point_ids if point_id not in chunk_refs)
    report.missing_vectors = sorted(chunk_id for chunk_id in chunk_refs if chunk_id not in point_ids)
    return report


def reconcile(
    *,
    apply: bool = False,
    stale_minutes: int = 30,
    purge_orphans: bool = False,
    store: Any = None,
) -> dict[str, Any]:
    """Return the planned repairs and, only with ``apply``, perform them."""
    report = inspect(stale_minutes=stale_minutes, store=store)
    plan: dict[str, Any] = {
        "ok": report.ok,
        "applied": False,
        "stale_to_fail": [str(item["id"]) for item in report.stale_processing],
        "orphan_chunks": report.orphan_chunks,
        "orphan_vectors": report.orphan_vectors,
        "missing_vectors": report.missing_vectors,
        "count_mismatches": report.count_mismatches,
        "vector_store_error": report.vector_store_error,
        "purged_chunks": 0,
        "purged_vectors": 0,
    }
    if not apply:
        return plan

    for document_id in plan["stale_to_fail"]:
        db.update_document(
            document_id,
            status="failed",
            error_message=RECONCILE_STALE_DETAIL,
        )
    if purge_orphans:
        plan["purged_chunks"] = db.delete_chunks(plan["orphan_chunks"])
        if report.vector_store_error is None:
            selected = store or get_store()
            plan["purged_vectors"] = selected.delete_points(plan["orphan_vectors"])

    plan["applied"] = True
    return plan
