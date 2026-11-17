"""Hybrid retrieval: BM25 lexical scoring + vector similarity, optional rerank.

Why not plain token overlap: with a bag-of-words embedder every question shares
"the"/"من" with every paragraph, so cosine similarity sits in one flat band and
the ranking is effectively random. The lexical side therefore ignores stopwords,
applies light stemming (Arabic plural/feminine/accusative endings, English
plurals) and weights terms with BM25 - inverse document frequency plus length
normalisation.

Two numbers come out of the lexical stage:

* ``bm25``     - how strongly this chunk matches the question (used for ranking)
* ``coverage`` - the share of the question's IDF mass present in the chunk

``coverage`` drives the abstention gate. With the offline hashing embedder a
chunk that covers less than a third of the question is not evidence, and the
pipeline answers "not found in the indexed documents" instead of quoting an
unrelated paragraph.
"""

from __future__ import annotations

import copy
import math
import re
import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable

from . import db
from .config import settings
from .embeddings import content_terms, get_embedder, tokenize
from .store import get_store
from .structure import (
    Heading,
    headings,
    match_heading,
    section_lines,
    section_window,
    starts_with_heading,
)

BM25_K1 = 1.2
BM25_B = 0.75

# "ابحث في كل الفصول" / "all sections": a scan question with no single title.
_BREADTH_RE = re.compile(
    r"(?:كل|جميع|كافة)\s+(?:ال)?(?:فصول|فصل|أقسام|اقسام|قسم)"
    r"|\b(?:all|every)\s+(?:chapters?|sections?)\b",
    re.IGNORECASE,
)
_SECTION_SCAN_LIMIT = 50


def _bm25_idf(total_chunks: int, document_frequency: int) -> float:
    return math.log(
        1.0
        + (total_chunks - document_frequency + 0.5) / (document_frequency + 0.5)
    )


@dataclass(frozen=True)
class _Corpus:
    """Term statistics for every indexed chunk, rebuilt only when data changes."""

    key: tuple[int, str]
    rows: tuple[tuple[str, str, Counter], ...]
    document_frequency: Counter
    average_length: float

    def scoped(self, document_ids: list[str] | None) -> "_Corpus":
        if not document_ids:
            return self
        allowed = set(document_ids)
        rows = tuple(row for row in self.rows if row[1] in allowed)
        frequency: Counter = Counter()
        for _, _, counts in rows:
            frequency.update(counts.keys())
        total = sum(sum(counts.values()) for _, _, counts in rows)
        return _Corpus(
            key=self.key,
            rows=rows,
            document_frequency=frequency,
            average_length=(total / len(rows)) if rows else 0.0,
        )


# One corpus per workspace. Term statistics computed from another workspace's
# chunks would leak its vocabulary through IDF weights and cache entries.
_corpus_cache: dict[str | None, _Corpus] = {}
_corpus_lock = threading.Lock()


def _corpus(workspace_id: str | None = None) -> _Corpus:
    key = db.chunks_version(workspace_id=workspace_id)
    cached = _corpus_cache.get(workspace_id)
    if cached is not None and cached.key == key:
        return cached
    with _corpus_lock:
        cached = _corpus_cache.get(workspace_id)
        if cached is not None and cached.key == key:
            return cached
        rows = tuple(
            (chunk["id"], chunk["document_id"], Counter(content_terms(chunk["text"])))
            for chunk in db.all_chunks(workspace_id=workspace_id)
        )
        frequency: Counter = Counter()
        for _, _, counts in rows:
            frequency.update(counts.keys())
        total = sum(sum(counts.values()) for _, _, counts in rows)
        built = _Corpus(
            key=key,
            rows=rows,
            document_frequency=frequency,
            average_length=(total / len(rows)) if rows else 0.0,
        )
        _corpus_cache[workspace_id] = built
        return built


def query_term_idf(
    terms: Iterable[str], workspace_id: str | None = None
) -> dict[str, float]:
    """BM25 IDF for each term, so callers can weigh rare evidence higher."""
    corpus = _corpus(workspace_id)
    total = len(corpus.rows) or 1
    return {
        term: _bm25_idf(total, corpus.document_frequency.get(term, 0))
        for term in set(terms)
    }


def _query_terms(query: str) -> set[str]:
    return set(content_terms(query)) or set(tokenize(query))


def _lexical_scores(
    query_terms: set[str],
    document_ids: list[str] | None,
    workspace_id: str | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return ``(bm25, coverage)`` per chunk, both in ``[0, 1]``."""
    if not query_terms:
        return {}, {}

    corpus = _corpus(workspace_id).scoped(document_ids)
    if not corpus.rows:
        return {}, {}

    total_chunks = len(corpus.rows)
    idf = {
        term: _bm25_idf(total_chunks, corpus.document_frequency.get(term, 0))
        for term in query_terms
    }
    total_idf = sum(idf.values()) or 1.0
    # Perfect match of every query term with saturated term frequency at average
    # length maps to 1.0, so BM25 scores stay comparable across questions.
    ceiling = total_idf * (BM25_K1 + 1.0)

    bm25: dict[str, float] = {}
    coverage: dict[str, float] = {}
    for chunk_id, _, counts in corpus.rows:
        length = sum(counts.values()) or 1
        length_factor = BM25_K1 * (
            1.0 - BM25_B + BM25_B * (length / (corpus.average_length or 1.0))
        )
        score = 0.0
        matched_idf = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            matched_idf += idf[term]
            score += idf[term] * (
                frequency * (BM25_K1 + 1.0) / (frequency + length_factor)
            )
        if score <= 0.0:
            continue
        bm25[chunk_id] = min(1.0, score / ceiling)
        coverage[chunk_id] = matched_idf / total_idf
    return bm25, coverage


def _using_hashing_embeddings() -> bool:
    return settings.embedding_backend not in {
        "st",
        "sentence-transformers",
        "sentence_transformers",
    }


def _section_anchor(
    query: str, ranked: list[dict[str, Any]]
) -> tuple[dict[str, Any], Heading, str] | None:
    """The retrieved chunk whose heading the question names, if any.

    A section-title question ("تنفيذ مرحلة التعرف على الوجه") is a near-exact
    match for the heading line, which often falls at the *end* of a chunk; the
    paragraphs that answer it live in the following chunks. Preferring a chunk
    whose first line is the matched heading keeps the body attached to the
    anchor. A breadth question ("كل الفصول") has no single title, so the best
    ranked chunk that carries any heading anchors the expansion instead.
    """
    best: tuple[tuple[float, bool, int], dict[str, Any], Heading] | None = None
    for position, chunk in enumerate(ranked[:_SECTION_SCAN_LIMIT]):
        matched = match_heading(query, chunk["text"])
        if matched is None:
            continue
        heading, quality = matched
        first = starts_with_heading(chunk["text"])
        # Tuple order matters: exact title coverage first, then a heading that
        # opens the chunk (body follows inside it), then retrieval rank.
        key = (quality, bool(first and first.number == heading.number), -position)
        if best is None or key > best[0]:
            best = (key, chunk, heading)
    if best is not None:
        return best[1], best[2], "title"

    if _BREADTH_RE.search(query):
        for chunk in ranked[:_SECTION_SCAN_LIMIT]:
            found = headings(chunk["text"])
            # The anchor must have a body to expand into; a TOC row does not.
            if found and section_lines(chunk["text"], after=found[0].line):
                return chunk, found[0], "breadth"
    return None


def _place_section(
    ranked: list[dict[str, Any]],
    section: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Insert the section body where the anchor ranked, keeping ``top_k``."""
    head = ranked[:top_k]
    anchor_id = section[0]["chunk_id"]
    if anchor_id not in {item["chunk_id"] for item in head}:
        return head
    section_ids = {item["chunk_id"] for item in section}
    anchor_position = next(
        position for position, item in enumerate(head) if item["chunk_id"] == anchor_id
    )
    rest = [item for item in head if item["chunk_id"] not in section_ids]
    insert_at = min(anchor_position, len(rest))
    return (rest[:insert_at] + section + rest[insert_at:])[:top_k]


def _expand_section(
    query: str,
    ranked: list[dict[str, Any]],
    top_k: int,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    """Attach the body of the section heading that the query names.

    The expansion never invents a score: siblings inherit the anchor's rank
    (minus a tiny offset so they keep reading order) and carry ``section``
    metadata, which the synthesizer uses to answer from the body instead of the
    heading or a figure caption inside the anchor chunk.
    """
    expand = settings.section_expand
    if expand <= 0 or not ranked:
        return ranked[:top_k]

    anchor = _section_anchor(query, ranked)
    if anchor is None:
        return ranked[:top_k]
    chunk, heading, mode = anchor
    anchor_score = float(chunk["score"])

    section: list[dict[str, Any]] = []
    anchor_item = dict(chunk)
    start, stop = section_window(chunk["text"], heading.number, after=heading.line)
    anchor_item["section"] = {
        "number": heading.number,
        "title": heading.title,
        "mode": mode,
        "anchor": True,
        "start_line": start,
        "stop_line": stop,
    }
    section.append(anchor_item)

    siblings = db.chunks_after(
        chunk["document_id"],
        chunk["chunk_index"],
        expand,
        workspace_id=workspace_id,
    )
    for offset, sibling in enumerate(siblings, start=1):
        start, stop = section_window(sibling["text"], heading.number)
        if start is None and stop == 0:
            # The chunk opens another section with nothing of ours before it.
            break
        score = round(max(0.0, anchor_score - 0.001 * offset), 4)
        section.append(
            {
                "chunk_id": sibling["id"],
                "document_id": sibling["document_id"],
                "document_filename": sibling.get("document_filename", ""),
                "chunk_index": sibling["chunk_index"],
                "text": sibling["text"],
                "score": score,
                "original_score": score,
                "coverage": 0.0,
                "metadata": sibling.get("metadata", {}),
                "section": {
                    "number": heading.number,
                    "title": heading.title,
                    "mode": mode,
                    "anchor": False,
                    "start_line": start,
                    "stop_line": stop,
                },
                "expanded": True,
            }
        )
        if stop is not None:
            # The next section starts inside this chunk; do not read past it.
            break
    return _place_section(ranked, section, top_k)


_cache: "OrderedDict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]]" = OrderedDict()
_cache_lock = threading.Lock()
_cache_stats = {"hits": 0, "misses": 0, "evictions": 0}


def _embedder_fingerprint() -> tuple[str, str, int]:
    return (
        settings.embedding_backend,
        settings.embedding_model,
        settings.embedding_dimension,
    )


def _cache_key(
    query: str,
    top_k: int,
    search_type: str,
    document_ids: list[str] | None,
    rerank: bool,
    workspace_id: str | None = None,
) -> tuple[Any, ...]:
    """Everything that can change a result list.

    ``chunks_version`` is the invalidation signal: it changes on every insert
    and delete, so a stale answer can never outlive a corpus change. The
    workspace is part of the key so two tenants never share cached hits.
    """
    return (
        workspace_id,
        db.chunks_version(workspace_id=workspace_id),
        " ".join(query.split()).casefold(),
        top_k,
        search_type,
        tuple(sorted(document_ids)) if document_ids else None,
        rerank,
        _embedder_fingerprint(),
    )


def _per_document_cache_key(
    query: str,
    top_k: int,
    per_document_top_k: int,
    search_type: str,
    document_ids: list[str] | None,
    rerank: bool,
    workspace_id: str | None = None,
) -> tuple[Any, ...]:
    return (
        workspace_id,
        db.chunks_version(workspace_id=workspace_id),
        " ".join(query.split()).casefold(),
        top_k,
        per_document_top_k,
        search_type,
        tuple(sorted(document_ids)) if document_ids else None,
        rerank,
        _embedder_fingerprint(),
    )


def per_document_search(
    query: str,
    *,
    top_k: int | None = None,
    per_document_top_k: int | None = None,
    search_type: str = "hybrid",
    document_ids: list[str] | None = None,
    rerank: bool = True,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve from every indexed document, then merge and re-rank globally.

    A single dominant document can otherwise fill the global top-K and hide a
    short but decisive passage in another file. Searching each document with its
    own quota makes every completed document a candidate; the final list is the
    same hit shape returned by :func:`hybrid_search`, so agents and citations do
    not need to know which strategy produced it.

    The query is embedded once even when several documents are searched. This
    matters for the optional API-backed embedders, where a per-document call
    would multiply quota usage for no quality gain.
    """
    top_k = max(1, min(top_k or settings.default_top_k, settings.max_top_k))
    per_document_top_k = max(
        1,
        min(
            per_document_top_k or settings.per_document_top_k,
            settings.max_top_k,
        ),
    )
    search_type = search_type if search_type in {"hybrid", "vector", "keyword"} else "hybrid"
    selected = db.completed_document_ids(document_ids, workspace_id=workspace_id)
    if not selected:
        return []

    key = _per_document_cache_key(
        query, top_k, per_document_top_k, search_type, selected, rerank, workspace_id
    )
    now = time.monotonic()
    if settings.search_cache_size > 0:
        with _cache_lock:
            entry = _cache.get(key)
            if entry is not None and now - entry[0] <= settings.search_cache_ttl_seconds:
                _cache.move_to_end(key)
                _cache_stats["hits"] += 1
                return copy.deepcopy(entry[1])
            if entry is not None:
                del _cache[key]
            _cache_stats["misses"] += 1

    # A keyword-only query needs no vector at all, so it pays no embedder cost.
    vector = None if search_type == "keyword" else get_embedder().embed_one(query)
    # Legacy callers (workspace_id=None) must keep the exact old call shape;
    # only a real workspace adds the scope keyword.
    scoped = {"workspace_id": workspace_id} if workspace_id is not None else {}
    merged: dict[str, dict[str, Any]] = {}
    for document_id in selected:
        hits = _hybrid_search_uncached(
            query,
            top_k=per_document_top_k,
            search_type=search_type,
            document_ids=[document_id],
            rerank=rerank,
            query_vector=vector,
            **scoped,
        )
        for hit in hits:
            previous = merged.get(hit["chunk_id"])
            if previous is None or hit["score"] > previous["score"]:
                merged[hit["chunk_id"]] = hit
    results = sorted(merged.values(), key=lambda item: item["score"], reverse=True)[:top_k]

    if settings.search_cache_size > 0:
        with _cache_lock:
            _cache[key] = (time.monotonic(), copy.deepcopy(results))
            _cache.move_to_end(key)
            while len(_cache) > settings.search_cache_size:
                _cache.popitem(last=False)
                _cache_stats["evictions"] += 1
    return results


def cache_stats() -> dict[str, Any]:
    with _cache_lock:
        return {
            **_cache_stats,
            "size": len(_cache),
            "maxsize": settings.search_cache_size,
            "ttl_seconds": settings.search_cache_ttl_seconds,
        }


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
        for name in _cache_stats:
            _cache_stats[name] = 0


def hybrid_search(
    query: str,
    *,
    top_k: int | None = None,
    search_type: str = "hybrid",
    document_ids: list[str] | None = None,
    rerank: bool = True,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    top_k = max(1, min(top_k or settings.default_top_k, settings.max_top_k))
    search_type = search_type if search_type in {"hybrid", "vector", "keyword"} else "hybrid"
    scoped = {"workspace_id": workspace_id} if workspace_id is not None else {}
    if settings.search_cache_size <= 0:
        return _hybrid_search_uncached(
            query,
            top_k=top_k,
            search_type=search_type,
            document_ids=document_ids,
            rerank=rerank,
            **scoped,
        )

    key = _cache_key(query, top_k, search_type, document_ids, rerank, workspace_id)
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is not None and now - entry[0] <= settings.search_cache_ttl_seconds:
            _cache.move_to_end(key)
            _cache_stats["hits"] += 1
            return copy.deepcopy(entry[1])
        if entry is not None:
            del _cache[key]
        _cache_stats["misses"] += 1

    results = _hybrid_search_uncached(
        query,
        top_k=top_k,
        search_type=search_type,
        document_ids=document_ids,
        rerank=rerank,
        **scoped,
    )

    with _cache_lock:
        # Deep copies on both sides: a caller that sorts or annotates its result
        # list must never mutate the cached answer.
        _cache[key] = (time.monotonic(), copy.deepcopy(results))
        _cache.move_to_end(key)
        while len(_cache) > settings.search_cache_size:
            _cache.popitem(last=False)
            _cache_stats["evictions"] += 1
    return results


def _hybrid_search_uncached(
    query: str,
    *,
    top_k: int | None = None,
    search_type: str = "hybrid",
    document_ids: list[str] | None = None,
    rerank: bool = True,
    query_vector: Any | None = None,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    top_k = max(1, min(top_k or settings.default_top_k, settings.max_top_k))
    search_type = search_type if search_type in {"hybrid", "vector", "keyword"} else "hybrid"
    hashing = _using_hashing_embeddings()

    query_terms = _query_terms(query)
    bm25_scores, coverage_scores = (
        _lexical_scores(query_terms, document_ids, workspace_id)
        if search_type in {"hybrid", "keyword"} or hashing
        else ({}, {})
    )

    if hashing and search_type in {"hybrid", "keyword"}:
        # No chunk covers enough of the question -> no evidence -> abstain.
        candidate_ids = {
            chunk_id
            for chunk_id, coverage in coverage_scores.items()
            if coverage >= settings.hashing_min_coverage
        }
        if not candidate_ids:
            return []
    else:
        candidate_ids = set(bm25_scores)

    vector_scores: dict[str, float] = {}
    if search_type in {"hybrid", "vector"}:
        vector = query_vector if query_vector is not None else get_embedder().embed_one(query)
        hits = get_store().search(
            vector,
            top_k=max(top_k * 6, 40),
            document_ids=document_ids,
            workspace_id=workspace_id,
        )
        vector_scores = {chunk_id: score for chunk_id, score, _ in hits}
        if hashing:
            # A hashing vector shares noise dimensions with unrelated text, so
            # only keep vector hits that also share a real content term.
            vector_scores = {
                chunk_id: score
                for chunk_id, score in vector_scores.items()
                if chunk_id in bm25_scores
            }
        candidate_ids |= set(vector_scores)

    if not candidate_ids:
        return []

    # The hashing "vector" is a lexical signature with no learned semantics; it
    # is a tie-breaker at best. A trained embedder earns a real half-share.
    vector_weight = (
        min(settings.hybrid_alpha, settings.hashing_vector_weight)
        if hashing
        else settings.hybrid_alpha
    )
    coverage_weight = settings.rerank_coverage_weight if rerank else 0.0

    chunk_rows = db.get_chunks(list(candidate_ids), workspace_id=workspace_id)

    results: list[dict[str, Any]] = []
    for chunk_id in candidate_ids:
        row = chunk_rows.get(chunk_id)
        if not row:
            continue

        vector_score = vector_scores.get(chunk_id, 0.0)
        bm25_score = bm25_scores.get(chunk_id, 0.0)
        coverage = coverage_scores.get(chunk_id, 0.0)

        if search_type == "keyword":
            base = bm25_score
        elif search_type == "vector":
            base = vector_score
        else:
            base = vector_weight * vector_score + (1.0 - vector_weight) * bm25_score

        score = (
            (1.0 - coverage_weight) * base + coverage_weight * coverage
            if coverage_weight
            else base
        )
        score = max(0.0, min(1.0, score))

        results.append(
            {
                "chunk_id": chunk_id,
                "document_id": row["document_id"],
                "document_filename": row.get("document_filename", ""),
                "chunk_index": row["chunk_index"],
                "text": row["text"],
                "score": round(score, 4),
                "original_score": round(base, 4),
                "coverage": round(coverage, 4),
                "metadata": row.get("metadata", {}),
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return _expand_section(query, results, top_k, workspace_id)
