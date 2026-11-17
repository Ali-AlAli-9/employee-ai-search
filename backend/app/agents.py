"""Multi-agent pipeline: Researcher -> Retriever -> Synthesizer.

The LLM is optional. Without an API key the pipeline still works using
deterministic heuristics, which keeps the demo functional at zero cost.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import db
from .byok import LLMSettings, resolve_llm, using_llm
from .embeddings import content_terms, tokenize
from .search import per_document_search, query_term_idf
from .structure import section_lines

RESEARCHER_SYSTEM = (
    "You are a Research Agent for an enterprise AI search system. "
    "Decompose the user question into 1-5 focused sub-queries and recommend a "
    "search strategy. Reply with JSON only: "
    '{"sub_queries": ["..."], "search_strategy": "hybrid|vector|keyword", '
    '"confidence": 0.0}'
)

SYNTHESIZER_SYSTEM = (
    "You are a Synthesizer Agent. Answer the question using ONLY the provided chunks. "
    "Add inline citation markers like [1], [2] that map to the chunk index. "
    "If the chunks do not contain the answer, say so honestly. Reply with JSON only: "
    '{"answer": "...", "citation_indices": [1, 2], "confidence": 0.0}'
)

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def _parse_json(raw: str) -> dict[str, Any] | None:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


class LLMClient:
    """OpenAI-compatible client that reads the *current request's* settings.

    The settings come from :mod:`app.byok`: either the deployment's key or a
    visitor-supplied one for this request only.
    """

    def complete_json(self, system: str, user: str) -> dict[str, Any] | None:
        config = resolve_llm()
        if not config.enabled:
            return None
        payload = {
            "model": config.model,
            "temperature": 0.1,
            "max_tokens": config.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = httpx.post(
                f"{config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=config.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _parse_json(content)
        except Exception:
            return None


llm = LLMClient()


# --------------------------------------------------------------------------- #
# Researcher
# --------------------------------------------------------------------------- #
def _heuristic_plan(query: str) -> dict[str, Any]:
    parts = re.split(r"[?؟;؛]|\band\b|\bو\b|,|،", query)
    sub_queries = [part.strip() for part in parts if len(part.strip()) > 3][:5]
    if not sub_queries:
        sub_queries = [query.strip()]
    return {
        "sub_queries": sub_queries,
        "search_strategy": "hybrid",
        "confidence": 0.5,
    }


def plan_query(query: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    context = ""
    if history:
        recent = history[-4:]
        context = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
    prompt = f"Conversation context:\n{context}\n\nQuestion: {query}"
    result = llm.complete_json(RESEARCHER_SYSTEM, prompt)
    if result and isinstance(result.get("sub_queries"), list) and result["sub_queries"]:
        strategy = str(result.get("search_strategy", "hybrid")).lower()
        if strategy not in {"hybrid", "vector", "keyword"}:
            strategy = "hybrid"
        return {
            "sub_queries": [str(q) for q in result["sub_queries"][:5]],
            "search_strategy": strategy,
            "confidence": float(result.get("confidence", 0.7) or 0.7),
        }
    return _heuristic_plan(query)


# --------------------------------------------------------------------------- #
# Retriever
# --------------------------------------------------------------------------- #
def retrieve(
    plan: dict[str, Any],
    *,
    top_k: int = 10,
    rerank: bool = True,
    document_ids: list[str] | None = None,
    workspace_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    started = time.perf_counter()
    # Request bodies are untrusted: narrow to completed documents that actually
    # belong to this workspace before any retrieval is attempted. An unscoped
    # (None) call keeps the legacy behaviour of passing ids straight through.
    if workspace_id is not None:
        document_ids = db.completed_document_ids(document_ids, workspace_id=workspace_id)
    # Keep the historical call shape for unscoped callers; only a real
    # workspace adds the new keyword to collaborators and test doubles.
    scoped = {"workspace_id": workspace_id} if workspace_id is not None else {}
    merged: dict[str, dict[str, Any]] = {}
    for sub_query in plan["sub_queries"]:
        hits = per_document_search(
            sub_query,
            top_k=top_k,
            search_type=plan.get("search_strategy", "hybrid"),
            document_ids=document_ids,
            rerank=rerank,
            **scoped,
        )
        for hit in hits:
            existing = merged.get(hit["chunk_id"])
            if existing is None or hit["score"] > existing["score"]:
                merged[hit["chunk_id"]] = hit
    chunks = sorted(merged.values(), key=lambda item: item["score"], reverse=True)
    # Re-uploaded or overlapping documents can yield identical chunks; keep the best
    # copy so citations and the synthesizer prompt are not duplicated.
    deduped: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    for chunk in chunks:
        fingerprint = " ".join(chunk["text"].lower().split())
        if fingerprint in seen_text:
            continue
        seen_text.add(fingerprint)
        deduped.append(chunk)
    chunks = deduped[:top_k]
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return chunks, elapsed_ms


# --------------------------------------------------------------------------- #
# Synthesizer
# --------------------------------------------------------------------------- #
def _prefer_language(chunks: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    """Put chunks in the requested language first without dropping the rest.

    Dropping them looked tidy but lost the answer: an English question against
    an Arabic report would keep only the English abstract and never see the
    chapter that holds the fact. Ordering keeps the answer language stable while
    leaving every retrieved chunk available as evidence.
    """
    if len(chunks) < 2:
        return chunks
    if language == "ar":
        preferred = [c for c in chunks if _ARABIC_RE.search(c["text"])]
    else:
        preferred = [c for c in chunks if not _ARABIC_RE.search(c["text"])]
    if not preferred:
        return chunks
    preferred_ids = {chunk["chunk_id"] for chunk in preferred}
    rest = [c for c in chunks if c["chunk_id"] not in preferred_ids]
    return preferred + rest


def build_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations = []
    for index, chunk in enumerate(chunks, start=1):
        citations.append(
            {
                "index": index,
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "document_filename": chunk.get("document_filename", ""),
                "chunk_index": chunk["chunk_index"],
                "text_snippet": chunk["text"][:300],
                "page_number": (chunk.get("metadata") or {}).get("page_number"),
                "page_label": (chunk.get("metadata") or {}).get("page_label"),
                "relevance_score": round(float(chunk["score"]), 4),
            }
        )
    return citations


NO_EVIDENCE_EN = (
    "I couldn't find relevant information in the indexed documents. "
    "Try rephrasing the question, or upload a document that covers this topic."
)
NO_EVIDENCE_AR = (
    "لم أجد معلومات ذات صلة في المستندات المفهرسة. "
    "جرّب إعادة صياغة السؤال أو ارفع مستنداً يغطي هذا الموضوع."
)


def _no_evidence(language: str) -> str:
    return NO_EVIDENCE_AR if language == "ar" else NO_EVIDENCE_EN


def _clean_sentence(text: str) -> str:
    """Strip markdown and source-bracket markers so answers read like prose."""
    text = re.sub(r"\[\s*\d+(?:\s*[-–]\s*\d+)?\s*\]", " ", text)
    text = re.sub(r"^\s*[#>\-*]+\s*", "", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


MAX_EVIDENCE_SENTENCES = 4
MAX_EVIDENCE_CHUNKS = 8
# "كم / عدد / مدة / قيمة / متى" ask for a quantity or a date, so a sentence that
# actually contains a number is much more likely to be the answer.
_QUANTITY_TOKENS = {"كم", "عدد", "مده", "قيمه", "متي", "كميه", "نسبه"}
_QUANTITY_EN = re.compile(r"\b(how many|how much|how long|what percentage|what year)\b", re.I)
_DIGIT_RE = re.compile(r"\d")


def _wants_number(query: str) -> bool:
    return bool(_QUANTITY_EN.search(query)) or bool(
        set(tokenize(query)) & _QUANTITY_TOKENS
    )


def _section_scope(
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Chunks that form the section body when the query names its title.

    The anchor is the chunk holding the matched heading; expanded siblings carry
    the same section number. Ordering keeps the anchor first so the body that
    follows its heading is read before the previous section's leftovers.
    """
    scoped = [
        chunk
        for chunk in chunks
        if (chunk.get("section") or {}).get("mode") == "title"
    ]
    if not scoped:
        return [], None
    anchor = next(
        (chunk for chunk in scoped if chunk["section"].get("anchor")), scoped[0]
    )
    number = anchor["section"]["number"]
    body = [chunk for chunk in scoped if chunk["section"]["number"] == number]
    body.sort(key=lambda chunk: (not chunk["section"].get("anchor"), chunk["chunk_index"]))
    return body, number


def _evidence_units(
    chunks: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], str, int, int]], bool]:
    """Candidate answer units as ``(chunk, text, chunk_order, position)``.

    Section-title questions use the section's prose lines and never fall back to
    a heading or a figure caption: the caption under a heading is the reason a
    question used to be answered with "الشكل (3-5) ...". Normal questions keep
    sentence splitting across the top evidence chunks.
    """
    section_chunks, _ = _section_scope(chunks)
    units: list[tuple[dict[str, Any], str, int, int]] = []
    if section_chunks:
        for order, chunk in enumerate(section_chunks):
            info = chunk["section"]
            # start_line/stop_line were computed when the section was expanded:
            # they cut the previous section's tail and the next section's head.
            start = info.get("start_line")
            stop = info.get("stop_line")
            for position, line in enumerate(
                section_lines(chunk["text"], after=start, before=stop)
            ):
                units.append((chunk, line, order, position))
        return units, True

    for order, chunk in enumerate(chunks[:MAX_EVIDENCE_CHUNKS]):
        text = chunk["text"].strip()
        text = re.sub(r"\n{2,}", "\n\n", text)
        text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?؟])\s+|\n+", text)
            if sentence.strip()
        ]
        prose = [(i, s) for i, s in enumerate(sentences) if not s.lstrip().startswith("#")]
        if not prose:
            prose = list(enumerate(sentences))
        for position, sentence in prose:
            units.append((chunk, sentence, order, position))
    return units, False


def _heuristic_synthesis(
    query: str,
    chunks: list[dict[str, Any]],
    language: str,
    workspace_id: str | None = None,
) -> tuple[str, float, list[dict[str, Any]]]:
    """Extractive answer that refuses to quote unrelated sentences.

    A sentence is only eligible when it shares at least one *content* term with
    the question, and sentences are ranked by the IDF mass of the question terms
    they cover: matching "threshold" or "0.32" counts for more than matching
    "system", which appears in almost every chunk. If nothing qualifies the
    pipeline says so instead of falling back to "the longest sentence in the
    chunk" - that fallback is how a question about annual leave used to get an
    answer about a solenoid.

    When the question names a section title, the section body is itself the
    evidence: a body line with no shared term is still the requested content, so
    the opening lines of the section are used instead of abstaining.
    """
    ordered_terms = list(dict.fromkeys(content_terms(query))) or list(
        dict.fromkeys(tokenize(query))
    )
    terms = set(ordered_terms)
    if not chunks or not terms:
        return _no_evidence(language), 0.0, []

    idf = query_term_idf(ordered_terms, workspace_id=workspace_id)
    total_idf = sum(idf.get(term, 1.0) for term in ordered_terms) or 1.0
    wants_number = _wants_number(query)

    units, section_mode = _evidence_units(chunks)
    if not units:
        return _no_evidence(language), 0.0, []

    # Score every unit, then keep the best ones (at most one per chunk). Taking
    # "the best sentence of the first four chunks" would hide the answer
    # whenever it sits in a lower-ranked chunk.
    candidates: list[tuple[tuple[float, ...], dict[str, Any], str, float]] = []
    for chunk, unit, order, position in units:
        matched = terms & set(content_terms(unit))
        if not matched and not section_mode:
            continue
        coverage = sum(idf.get(term, 1.0) for term in matched) / total_idf
        numeric_bonus = 0.25 if (wants_number and _DIGIT_RE.search(unit)) else 0.0
        key = (
            coverage + numeric_bonus,
            coverage,
            len(matched),
            len(unit) >= 30,
            -order,
            -position,
        )
        candidates.append((key, chunk, _clean_sentence(unit), coverage))

    candidates.sort(key=lambda item: item[0], reverse=True)

    selected: list[tuple[dict[str, Any], str, float]] = []
    seen_chunks: set[str] = set()
    seen_text: set[str] = set()
    for _, chunk, sentence, coverage in candidates:
        # Normal questions keep at most one sentence per chunk so four different
        # sources are represented. A section body is one source: all of its
        # lines belong together and may contribute several sentences.
        if not section_mode and chunk["chunk_id"] in seen_chunks:
            continue
        if not sentence:
            continue
        fingerprint = sentence.lower()
        if fingerprint in seen_text:
            continue
        seen_chunks.add(chunk["chunk_id"])
        seen_text.add(fingerprint)
        selected.append((chunk, sentence, coverage))
        if len(selected) >= MAX_EVIDENCE_SENTENCES:
            break

    if not selected and section_mode:
        # The section was identified by its exact title, so its opening prose is
        # the answer even if it does not repeat the question's words.
        for chunk, unit, _, _ in units:
            sentence = _clean_sentence(unit)
            if not sentence or chunk["chunk_id"] in seen_chunks:
                continue
            seen_chunks.add(chunk["chunk_id"])
            selected.append((chunk, sentence, 0.0))
            if len(selected) >= 2:
                break

    if not selected:
        return _no_evidence(language), 0.0, []

    header = (
        "بناءً على المستندات المفهرسة:"
        if language == "ar"
        else "Based on the indexed documents:"
    )
    # Several selected sentences can come from the same section chunk, so the
    # citation number is assigned per unique chunk, not per sentence.
    citation_index: dict[str, int] = {}
    used_chunks: list[dict[str, Any]] = []
    lines: list[str] = []
    for chunk, sentence, _ in selected:
        if chunk["chunk_id"] not in citation_index:
            used_chunks.append(chunk)
            citation_index[chunk["chunk_id"]] = len(used_chunks)
        lines.append(f"- {sentence} [{citation_index[chunk['chunk_id']]}]")
    coverages = [coverage for _, _, coverage in selected]
    sentence_coverage = sum(coverages) / len(coverages)
    top_scores = sorted((float(c["score"]) for c in used_chunks), reverse=True)[:3]
    retrieval_score = sum(top_scores) / max(1, len(top_scores))
    confidence = 0.6 * sentence_coverage + 0.4 * retrieval_score
    confidence = round(max(0.0, min(0.9, confidence)), 4)
    return header + "\n" + "\n".join(lines), confidence, used_chunks


def synthesize(
    query: str,
    chunks: list[dict[str, Any]],
    language: str = "en",
    history: list[dict[str, Any]] | None = None,
    workspace_id: str | None = None,
) -> tuple[str, list[dict[str, Any]], float]:
    if not chunks:
        answer, confidence, _ = _heuristic_synthesis(
            query, chunks, language, workspace_id=workspace_id
        )
        return answer, [], confidence

    compact = [
        {
            "index": index,
            "filename": chunk.get("document_filename", ""),
            "text": chunk["text"][:1500],
        }
        for index, chunk in enumerate(chunks[:MAX_EVIDENCE_CHUNKS], start=1)
    ]
    prompt = json.dumps(
        {"question": query, "language": language, "chunks": compact}, ensure_ascii=False
    )
    result = llm.complete_json(SYNTHESIZER_SYSTEM, prompt)

    if result and isinstance(result.get("answer"), str) and result["answer"].strip():
        answer = result["answer"].strip()
        citations = build_citations(chunks)
        used_indices = result.get("citation_indices") or []
        if isinstance(used_indices, list):
            selected = [
                citation
                for citation in citations
                if citation["index"] in {int(i) for i in used_indices if str(i).isdigit()}
            ]
            if selected:
                citations = selected
        try:
            confidence = float(result.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        return answer, citations, round(max(0.0, min(1.0, confidence)), 4)

    answer, confidence, used_chunks = _heuristic_synthesis(
        query, chunks, language, workspace_id=workspace_id
    )
    return answer, build_citations(used_chunks), confidence


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
@dataclass
class PipelineResult:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    chunks: list[dict[str, Any]] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)
    strategy: str = "hybrid"
    trace: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    # Surfaced to the chat response so the UI can distinguish a model answer
    # from the deterministic fallback without parsing the answer text.
    llm_source: str = "none"


class Orchestrator:
    def run(
        self,
        query: str,
        *,
        history: list[dict[str, Any]] | None = None,
        language: str = "en",
        top_k: int = 10,
        search_type: str = "hybrid",
        rerank: bool = True,
        document_ids: list[str] | None = None,
        llm_config: LLMSettings | None = None,
        workspace_id: str | None = None,
    ) -> PipelineResult:
        # The override is scoped to this call: the stream generator and the
        # blocking path both invoke run(), so nothing outlives the request.
        with using_llm(llm_config):
            return self._run(
                query,
                history=history,
                language=language,
                top_k=top_k,
                search_type=search_type,
                rerank=rerank,
                document_ids=document_ids,
                workspace_id=workspace_id,
            )

    def _run(
        self,
        query: str,
        *,
        history: list[dict[str, Any]] | None = None,
        language: str = "en",
        top_k: int = 10,
        search_type: str = "hybrid",
        rerank: bool = True,
        document_ids: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> PipelineResult:
        started = time.perf_counter()
        history = history or []
        llm_settings = resolve_llm()
        # A disabled server configuration still carries the "server" label, but
        # no provider was called: report the answer's real provenance.
        llm_source = llm_settings.source if llm_settings.enabled else "none"

        plan_started = time.perf_counter()
        plan = plan_query(query, history)
        plan_ms = int((time.perf_counter() - plan_started) * 1000)

        plan["search_strategy"] = search_type if search_type in {"hybrid", "vector", "keyword"} else plan["search_strategy"]
        chunks, retrieval_ms = retrieve(
            plan,
            top_k=top_k,
            rerank=rerank,
            document_ids=document_ids,
            workspace_id=workspace_id,
        )
        chunks = _prefer_language(chunks, language)

        synth_started = time.perf_counter()
        answer, citations, confidence = synthesize(
            query, chunks, language, history, workspace_id=workspace_id
        )
        synth_ms = int((time.perf_counter() - synth_started) * 1000)

        total_ms = int((time.perf_counter() - started) * 1000)
        trace = {
            "researcher": {
                "sub_queries": plan["sub_queries"],
                "strategy": plan["search_strategy"],
                "duration_ms": plan_ms,
            },
            "retriever": {"chunks": len(chunks), "duration_ms": retrieval_ms},
            "synthesizer": {"duration_ms": synth_ms, "confidence": confidence},
            "llm_enabled": llm_settings.enabled,
            "llm_source": llm_source,
        }
        return PipelineResult(
            answer=answer,
            citations=citations,
            confidence=confidence,
            chunks=chunks,
            sub_queries=plan["sub_queries"],
            strategy=plan["search_strategy"],
            trace=trace,
            latency_ms=total_ms,
            llm_source=llm_source,
        )


orchestrator = Orchestrator()
