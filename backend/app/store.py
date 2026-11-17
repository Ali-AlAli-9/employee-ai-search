"""Vector store abstraction.

Default is a local, binary file-backed cosine store (zero infrastructure, works
on the Render free tier). When QDRANT_URL is configured, a Qdrant adapter is
used instead.

Why binary: the old JSON file was rewritten on every upload and parsed in full
on every boot, and search walked every point with a Python-level dot product.
A ``float32`` ``.npz`` archive loads in one call, and the cached, normalised
matrix turns a search into a single ``matrix @ query`` operation.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from .config import settings

logger = logging.getLogger(__name__)


class LocalVectorStore:
    def __init__(self, path: Path, legacy_path: Path | None = None) -> None:
        self.path = path
        self.legacy_path = (
            legacy_path if legacy_path is not None else path.with_suffix(".json")
        )
        self._ids: list[str] = []
        self._vectors: dict[str, np.ndarray] = {}
        self._payloads: dict[str, dict[str, Any]] = {}
        self._matrix: np.ndarray | None = None
        self._row_ids: list[str] = []
        self._dim: int | None = None
        self._dirty = True
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        if not self.path.exists():
            self._migrate_legacy()
            # `_migrate_legacy` already populated the in-memory maps and wrote
            # the archive; re-reading it would duplicate every point.
            return
        try:
            with np.load(self.path, allow_pickle=False) as data:
                ids = [str(value) for value in data["ids"]]
                matrix = np.asarray(data["vectors"], dtype=np.float32)
                payloads = [json.loads(str(value)) for value in data["payloads"]]
                stored_dim = int(data["dim"]) if "dim" in data.files else matrix.shape[1]
            if len(ids) != matrix.shape[0] or len(ids) != len(payloads):
                raise ValueError("array lengths differ")
            for index, point_id in enumerate(ids):
                self._ids.append(point_id)
                self._vectors[point_id] = matrix[index]
                self._payloads[point_id] = payloads[index]
            self._dim = stored_dim or None
            self._dirty = True
        except Exception as exc:  # noqa: BLE001 - a corrupt file must not stop boot
            logger.warning("could not read vector store %s: %s", self.path, exc)
            self._reset()

    def _migrate_legacy(self) -> None:
        """Read the pre-002 JSON store and write the binary format."""
        if not self.legacy_path.exists():
            return
        try:
            data = json.loads(self.legacy_path.read_text(encoding="utf-8"))
            points = data.get("points", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read legacy vector store %s: %s", self.legacy_path, exc)
            return

        dimension: int | None = None
        for point in points:
            try:
                vector = np.asarray(point["vector"], dtype=np.float32).reshape(-1)
                point_id = str(point["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if dimension is None:
                dimension = int(vector.size)
            if vector.size != dimension:
                continue
            self._ids.append(point_id)
            self._vectors[point_id] = vector
            self._payloads[point_id] = dict(point.get("payload", {}))
        self._dim = dimension
        self._dirty = True
        if self._ids:
            self._save()
            logger.info(
                "migrated %d vectors from %s to %s",
                len(self._ids),
                self.legacy_path,
                self.path,
            )

    def _reset(self) -> None:
        self._ids = []
        self._vectors = {}
        self._payloads = {}
        self._matrix = None
        self._row_ids = []
        self._dim = None
        self._dirty = True

    # ------------------------------------------------------------------ save
    def _save(self) -> None:
        ids = list(self._ids)
        if ids:
            vectors = np.stack([self._vectors[point_id] for point_id in ids])
            payloads = np.array(
                [
                    json.dumps(self._payloads[point_id], ensure_ascii=False)
                    for point_id in ids
                ],
                dtype=str,
            )
        else:
            vectors = np.zeros((0, self._dim or 0), dtype=np.float32)
            payloads = np.array([], dtype=str)
        tmp = self.path.with_suffix(".npz.tmp")
        with open(tmp, "wb") as handle:
            np.savez(
                handle,
                ids=np.array(ids, dtype=str),
                vectors=vectors.astype(np.float32, copy=False),
                payloads=payloads,
                dim=np.int64(self._dim or 0),
            )
        tmp.replace(self.path)

    # ------------------------------------------------------------------ write
    def upsert(self, points: list[dict[str, Any]]) -> None:
        if not points:
            return
        with self._lock:
            # Validate the whole batch before mutating anything: a rejected
            # 3-d point must not leave a half-written 2-d store behind.
            prepared: list[tuple[str, np.ndarray, dict[str, Any]]] = []
            expected_dim = self._dim
            for point in points:
                vector = np.asarray(point["vector"], dtype=np.float32).reshape(-1)
                if expected_dim is None:
                    expected_dim = int(vector.size)
                elif vector.size != expected_dim:
                    raise ValueError(
                        f"Embedding dimension changed: the store holds "
                        f"{expected_dim}-d vectors but this batch is "
                        f"{vector.size}-d. Restore the previous EMBEDDING_* "
                        "settings, or wipe DATA_DIR and re-upload."
                    )
                prepared.append(
                    (str(point["id"]), vector, dict(point.get("payload", {})))
                )
            self._dim = expected_dim
            for point_id, vector, payload in prepared:
                if point_id not in self._vectors:
                    self._ids.append(point_id)
                self._vectors[point_id] = vector
                self._payloads[point_id] = payload
            self._dirty = True
            self._save()

    def delete_document(
        self, document_id: str, workspace_id: str | None = None
    ) -> None:
        with self._lock:
            removed = [
                point_id
                for point_id in self._ids
                if self._payloads[point_id].get("document_id") == document_id
                and (
                    workspace_id is None
                    or self._payloads[point_id].get("workspace_id") == workspace_id
                )
            ]
            if not removed:
                return
            for point_id in removed:
                self._vectors.pop(point_id, None)
                self._payloads.pop(point_id, None)
            gone = set(removed)
            self._ids = [point_id for point_id in self._ids if point_id not in gone]
            self._dirty = True
            self._save()

    def count(self) -> int:
        return len(self._ids)

    def all_points(self) -> list[tuple[str, dict[str, Any]]]:
        """Expose stored payloads for the read-only consistency checker."""
        with self._lock:
            return [(point_id, dict(self._payloads[point_id])) for point_id in self._ids]

    def delete_points(self, point_ids: list[str]) -> int:
        """Delete explicit point ids; used only by the opt-in repair command."""
        wanted = {str(point_id) for point_id in point_ids}
        if not wanted:
            return 0
        with self._lock:
            removed = [point_id for point_id in self._ids if point_id in wanted]
            if not removed:
                return 0
            gone = set(removed)
            for point_id in removed:
                self._vectors.pop(point_id, None)
                self._payloads.pop(point_id, None)
            self._ids = [point_id for point_id in self._ids if point_id not in gone]
            self._dirty = True
            self._save()
            return len(removed)

    # ----------------------------------------------------------------- search
    def _ensure_matrix(self) -> None:
        if not self._dirty and self._matrix is not None:
            return
        if not self._ids or not self._dim:
            self._matrix = None
            self._row_ids = []
            self._dirty = False
            return
        matrix = np.stack([self._vectors[point_id] for point_id in self._ids])
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        self._matrix = (matrix / norms).astype(np.float32, copy=False)
        self._row_ids = list(self._ids)
        self._dirty = False

    def search(
        self,
        vector: Any,
        top_k: int = 10,
        document_ids: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        query = np.asarray(vector, dtype=np.float32).reshape(-1)
        query_norm = float(np.linalg.norm(query))
        if query_norm == 0.0:
            return []
        with self._lock:
            self._ensure_matrix()
            matrix = self._matrix
            if matrix is None or matrix.shape[1] != query.shape[0]:
                return []
            scores = matrix @ (query / query_norm)
            if document_ids or workspace_id is not None:
                allowed = set(document_ids) if document_ids else None
                mask = np.fromiter(
                    (
                        (
                            (
                                allowed is None
                                or self._payloads[point_id].get("document_id") in allowed
                            )
                            and (
                                workspace_id is None
                                or self._payloads[point_id].get("workspace_id")
                                == workspace_id
                            )
                        )
                        for point_id in self._row_ids
                    ),
                    dtype=bool,
                    count=len(self._row_ids),
                )
                candidates = np.flatnonzero(mask)
            else:
                candidates = np.arange(len(self._row_ids))
            if candidates.size == 0:
                return []
            limit = max(1, min(int(top_k), candidates.size))
            candidate_scores = scores[candidates]
            if candidates.size > limit:
                best = np.argpartition(-candidate_scores, limit - 1)[:limit]
            else:
                best = np.arange(candidates.size)
            order = best[np.argsort(-candidate_scores[best], kind="stable")]
            results: list[tuple[str, float, dict[str, Any]]] = []
            for position in order:
                row = int(candidates[int(position)])
                cosine = float(scores[row])
                score = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
                point_id = self._row_ids[row]
                results.append((point_id, score, self._payloads[point_id]))
            return results


class QdrantStore:
    """Thin Qdrant adapter (optional dependency)."""

    def __init__(self) -> None:
        from qdrant_client import QdrantClient  # type: ignore
        from qdrant_client.models import Distance, VectorParams  # type: ignore

        from .embeddings import get_embedder

        self._client = QdrantClient(
            url=settings.qdrant_url, api_key=settings.qdrant_api_key or None
        )
        self._collection = settings.qdrant_collection
        # An API model knows its own width; do not create a collection with the
        # configured fallback when the real embedder differs.
        dimension = getattr(get_embedder(), "dimension", settings.embedding_dimension)
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )

    def upsert(self, points: list[dict[str, Any]]) -> None:
        from qdrant_client.models import PointStruct  # type: ignore

        self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(
                    id=point["id"],
                    vector=[float(x) for x in point["vector"]],
                    payload=point.get("payload", {}),
                )
                for point in points
            ],
        )

    def delete_document(
        self, document_id: str, workspace_id: str | None = None
    ) -> None:
        from qdrant_client.models import (  # type: ignore
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )

        must = [
            FieldCondition(key="document_id", match=MatchValue(value=document_id))
        ]
        if workspace_id is not None:
            must.append(
                FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id))
            )
        self._client.delete(
            collection_name=self._collection,
            points_selector=FilterSelector(filter=Filter(must=must)),
        )

    def count(self) -> int:
        return int(self._client.count(collection_name=self._collection).count)

    def all_points(self) -> list[tuple[str, dict[str, Any]]]:
        points: list[tuple[str, dict[str, Any]]] = []
        offset: Any = None
        while True:
            batch, offset = self._client.scroll(
                collection_name=self._collection,
                scroll_filter=None,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            points.extend((str(point.id), dict(point.payload or {})) for point in batch)
            if offset is None or not batch:
                return points

    def delete_points(self, point_ids: list[str]) -> int:
        if not point_ids:
            return 0
        self._client.delete(
            collection_name=self._collection,
            points_selector=[str(point_id) for point_id in point_ids],
            wait=True,
        )
        return len(point_ids)

    def search(
        self,
        vector: Any,
        top_k: int = 10,
        document_ids: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        from qdrant_client.models import (  # type: ignore
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        must: list[Any] = []
        if document_ids:
            must.append(
                FieldCondition(
                    key="document_id", match=MatchAny(any=list(document_ids))
                )
            )
        if workspace_id is not None:
            must.append(
                FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id))
            )
        query_filter = Filter(must=must) if must else None
        try:
            hits = self._client.search(
                collection_name=self._collection,
                query_vector=[float(x) for x in vector],
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
            )
        except AttributeError:  # newer qdrant-client API
            response = self._client.query_points(
                collection_name=self._collection,
                query=[float(x) for x in vector],
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
            )
            hits = response.points
        return [
            (
                str(hit.id),
                max(0.0, min(1.0, (float(hit.score) + 1.0) / 2.0)),
                dict(hit.payload or {}),
            )
            for hit in hits
        ]


_store = None
_store_lock = threading.Lock()


def get_store():
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                if settings.qdrant_url:
                    try:
                        _store = QdrantStore()
                    except Exception:
                        _store = LocalVectorStore(
                            settings.vectors_path, settings.legacy_vectors_path
                        )
                else:
                    _store = LocalVectorStore(
                        settings.vectors_path, settings.legacy_vectors_path
                    )
    return _store
