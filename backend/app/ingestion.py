"""Document extraction, chunking and indexing pipeline."""

from __future__ import annotations

import io
import logging
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from . import db
from .config import settings
from .embeddings import get_embedder
from .store import get_store

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}

# The real exception is logged in full below. Only this stable, secret-free text
# is persisted and shown in the document list; raw str(exc) can contain file
# paths, database URLs or provider request ids.
INGESTION_FAILURE_DETAIL = "The document could not be processed. Please try again."

# --------------------------------------------------------------------------- #
# Extraction artefacts
# --------------------------------------------------------------------------- #
_ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_ARABIC_WORD_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")
_ARTIFACT_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\uf000-\uf8ff]")
# Table-of-contents dotted leaders ("1-5 أهداف المشروع .........."), including
# PDFs that render spaced dots.
_TOC_DOTTED_RE = re.compile(r"(?:\.\s*){3,}")
_BIDI_GLUE = "\u200c\u200d"  # ZWNJ / ZWJ keep their base letter
_ARABIC_FUNCTION_WORDS = frozenset(
    "في من على إلى هذا عن أن كان ذلك عند بعد قبل كل بين ثم قد مع غير الذي التي".split()
)
_REVERSED_MARK_MIN_HITS = 2


def _chars_with_clusters(text: str) -> list[str]:
    """Split into grapheme clusters so combining marks stay with their base."""
    clusters: list[str] = []
    for char in text:
        if unicodedata.combining(char) or char in _BIDI_GLUE:
            if clusters:
                clusters[-1] += char
            else:
                clusters.append(char)
        else:
            clusters.append(char)
    return clusters


def _reverse_visual_order_line(line: str) -> str:
    """Rebuild a visually-ordered (mirrored) line into logical Arabic order.

    Reverses the order of directional runs *and* reverses each Arabic run's
    characters. Non-Arabic runs (digits, Latin, punctuation) keep their internal
    order, so "2023" survives intact.
    """
    runs: list[tuple[bool, str]] = []
    index, length = 0, len(line)
    while index < length:
        end = index
        is_arabic = _ARABIC_CHAR_RE.match(line[index]) is not None
        while end < length and (
            (_ARABIC_CHAR_RE.match(line[end]) is not None) == is_arabic
        ):
            end += 1
        runs.append((is_arabic, line[index:end]))
        index = end
    out: list[str] = []
    for is_arabic, run in reversed(runs):
        if is_arabic:
            out.append("".join(reversed(_chars_with_clusters(run))))
        else:
            out.append(run)
    return "".join(out)


def _looks_visually_reversed_arabic(text: str) -> bool:
    """Detect visual-order extraction with two conservative signals.

    1. Reversed "ال" prefix: normal words start with «ال», mirrored words end
       with «لا».
    2. Function words: «في/من/على» appear as «يف/نم/ىلع» when mirrored.
    """
    words = _ARABIC_WORD_RE.findall(text)
    la_ending = sum(1 for word in words if len(word) >= 3 and word.endswith("لا"))
    al_starting = sum(1 for word in words if len(word) >= 3 and word.startswith("ال"))
    if la_ending > al_starting and la_ending >= _REVERSED_MARK_MIN_HITS:
        return True

    reversed_hits = 0
    normal_hits = 0
    for word in words:
        if word in _ARABIC_FUNCTION_WORDS:
            normal_hits += 1
        elif word[::-1] in _ARABIC_FUNCTION_WORDS:
            reversed_hits += 1
    return reversed_hits > normal_hits and reversed_hits >= _REVERSED_MARK_MIN_HITS


def _normalize_pdf_arabic(text: str) -> str:
    """Clean pypdf artefacts and restore logical order for visual-order PDFs.

    Applied to PDF text only: .txt and .docx sources already store logical order.
    Pure Latin and normal-order Arabic pass through untouched, so detection only
    rewrites text that is clearly mirrored.
    """
    text = _ARTIFACT_RE.sub("", text).replace("\r", "")
    text = unicodedata.normalize("NFKC", text)
    if not _ARABIC_CHAR_RE.search(text):
        return text
    if not _looks_visually_reversed_arabic(text):
        return text
    return "\n".join(
        _reverse_visual_order_line(line) if _ARABIC_CHAR_RE.search(line) else line
        for line in text.split("\n")
    )


def _is_toc_only_chunk(text: str) -> bool:
    """True when a chunk is table-of-contents material and carries no prose.

    Index lines are near-exact matches for any question that reuses a section
    title, so they silently outrank the real section body. Two shapes are
    rejected: every line is a dotted leader, or at least two leader lines make
    up half of a mixed index page. Prose always wins over a stray leader line.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return False
    dotted = sum(1 for line in lines if _TOC_DOTTED_RE.search(line))
    if dotted == len(lines):
        return True
    return len(lines) >= 2 and dotted >= 2 and dotted / len(lines) >= 0.5


@dataclass
class ExtractedPage:
    """One source page.

    ``page_number`` is always the physical position inside the file (1-based),
    which never lies. ``page_label`` is the number a reader sees printed on the
    page, when the document tells us: PDF ``/PageLabels`` first, then a
    conservative running-number detection (front matter shifts printed page 30
    to PDF page 38, and citing 38 is confusing).
    """

    page_number: int | None
    text: str
    page_label: str | None = None


# Standalone page-number line, optionally wrapped in dashes ("- 30 -"), Latin
# or Arabic-Indic digits. Running heads that mix a number with words are
# deliberately ignored: only a line that is *only* a number is evidence.
def _pdf_page_labels(reader: Any) -> list[str | None]:
    """Read the PDF ``/PageLabels`` tree, tolerating malformed documents."""
    try:
        raw = list(reader.page_labels)
    except Exception:  # noqa: BLE001 - a broken label tree is not fatal
        return []
    labels: list[str | None] = []
    for value in raw:
        label = str(value).strip() if value is not None else ""
        labels.append(label or None)
    return labels





def _extract_pdf(content: bytes) -> list[ExtractedPage]:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(io.BytesIO(content))
    labels = _pdf_page_labels(reader)
    pages: list[ExtractedPage] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if settings.pdf_visual_order_repair:
            text = _normalize_pdf_arabic(text)
        if text.strip():
            label = labels[index - 1] if index <= len(labels) else None
            if label == str(index):
                # Same as the physical page: no need to carry a second value.
                label = None
            pages.append(ExtractedPage(page_number=index, text=text, page_label=label))
    if pages:
        logger.info(
            "pdf page labels: source=/PageLabels labelled=%s pages=%s",
            sum(1 for page in pages if page.page_label),
            len(pages),
        )
    return pages


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W_TEXT = f"{_W}t"
_W_TAB = f"{_W}tab"
_W_BREAK = f"{_W}br"
_W_CARRIAGE_RETURN = f"{_W}cr"
_W_RENDERED_BREAK = f"{_W}lastRenderedPageBreak"


def _docx_text_events(element) -> Iterator[tuple[str, str]]:
    """Yield ``("text", value)`` and ``("break", "")`` in document order.

    ``Paragraph.text`` flattens a paragraph and drops page information, so the
    underlying runs are walked directly: ``w:t`` carries the text, and both an
    explicit ``w:br w:type="page"`` and Word's ``w:lastRenderedPageBreak`` mark
    the start of a new page.
    """
    for node in element.iter():
        tag = node.tag
        if tag == _W_TEXT:
            yield "text", node.text or ""
        elif tag == _W_TAB:
            yield "text", " "
        elif tag == _W_CARRIAGE_RETURN:
            yield "text", "\n"
        elif tag == _W_BREAK:
            if node.get(f"{_W}type") == "page":
                yield "break", ""
            else:
                yield "text", "\n"
        elif tag == _W_RENDERED_BREAK:
            yield "break", ""


def _extract_docx(content: bytes) -> list[ExtractedPage]:
    import docx  # type: ignore
    from docx.table import Table  # type: ignore

    document = docx.Document(io.BytesIO(content))
    pages: dict[int, list[str]] = {}
    order: list[int] = []
    page = 1
    saw_break = False

    def append(text: str) -> None:
        text = text.strip()
        if not text:
            return
        if page not in pages:
            pages[page] = []
            order.append(page)
        pages[page].append(text)

    # `document.paragraphs` skips tables, which is where reports and specs put
    # thresholds, test results and pin maps. Walk the body in document order.
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            buffer: list[str] = []
            for kind, value in _docx_text_events(child):
                if kind == "break":
                    append("".join(buffer))
                    buffer = []
                    page += 1
                    saw_break = True
                else:
                    buffer.append(value)
            append("".join(buffer))
        elif tag == "tbl":
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                line = " | ".join(cell for cell in cells if cell)
                append(line)

    if not saw_break:
        # Word's page layout is not stored in the file. Without a break marker
        # any page number would be invented, so keep the PDF-style `None`.
        text = "\n".join(line for number in order for line in pages[number]).strip()
        return [ExtractedPage(page_number=None, text=text)] if text.strip() else []

    return [
        ExtractedPage(page_number=number, text="\n".join(pages[number]))
        for number in sorted(order)
    ]


def _extract_text(content: bytes) -> list[ExtractedPage]:
    for encoding in ("utf-8", "utf-16", "cp1256", "latin-1"):
        try:
            text = content.decode(encoding)
            if text.strip():
                return [ExtractedPage(page_number=None, text=text)]
        except UnicodeDecodeError:
            continue
    return []


def extract_pages(filename: str, content: bytes) -> list[ExtractedPage]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        pages = _extract_pdf(content)
        if pages:
            return pages
        return _extract_text(content)
    if suffix == ".docx":
        pages = _extract_docx(content)
        if pages:
            return pages
        return _extract_text(content)
    return _extract_text(content)


def chunk_text(text: str, size_tokens: int, overlap_tokens: int) -> list[str]:
    """Character-based chunking with whitespace-aware boundaries (~4 chars/token)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    size = max(100, size_tokens * 4)
    overlap = max(0, min(overlap_tokens * 4, size // 2))
    step = max(1, size - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            # Prefer a paragraph break, then a line break, then a space.
            search_from = start + int(size * 0.6)
            boundary = text.rfind("\n\n", search_from, end)
            if boundary <= start:
                boundary = text.rfind("\n", search_from, end)
            if boundary <= start:
                boundary = text.rfind(" ", search_from, end)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece and not (settings.toc_filter and _is_toc_only_chunk(piece)):
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _build_chunks(document_id: str, pages: list[ExtractedPage]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    index = 0
    created_at = db.now_iso()
    for page in pages:
        for piece in chunk_text(
            page.text, settings.chunk_size_tokens, settings.chunk_overlap_tokens
        ):
            metadata: dict[str, Any] = {"page_number": page.page_number}
            if page.page_label:
                # The printed page a reader can find; page_number stays the
                # physical PDF page so an offset can always be reconstructed.
                metadata["page_label"] = page.page_label
            records.append(
                {
                    "id": str(uuid.uuid4()),
                    "document_id": document_id,
                    "chunk_index": index,
                    "text": piece,
                    "token_count": max(1, len(piece) // 4),
                    "metadata": metadata,
                    "created_at": created_at,
                }
            )
            index += 1
    return records


def ingest_document(
    document_id: str,
    filename: str,
    content: bytes,
    *,
    workspace_id: str | None = None,
) -> None:
    """Background ingestion task: parse -> chunk -> embed -> index.

    ``workspace_id`` is carried on every stored artefact so retrieval can filter
    by tenant. ``None`` keeps the legacy, unscoped behaviour.
    """
    started = time.perf_counter()
    # An unscoped call keeps the exact legacy call shape for DB helpers and
    # their test doubles; a real workspace is always threaded through.
    scoped = {"workspace_id": workspace_id} if workspace_id is not None else {}
    try:
        db.update_document(document_id, status="processing", **scoped)
        if db.get_document(document_id, **scoped) is None:
            # Deleted (or replaced) between upload and the worker starting.
            logger.info("ingestion skipped document=%s (deleted before start)", document_id)
            return
        pages = extract_pages(filename, content)
        if not pages:
            raise ValueError("No extractable text found in document")

        records = _build_chunks(document_id, pages)
        if not records:
            raise ValueError("Document produced no chunks")
        limit = settings.max_chunks_per_document
        if len(records) > limit:
            raise ValueError(
                f"Document produced {len(records)} chunks, above the {limit}-chunk "
                "limit. Split it into smaller files (or raise MAX_CHUNKS_PER_DOCUMENT)."
            )

        embedder = get_embedder()
        points = []
        batch_size = max(1, settings.embedding_batch_size)
        # Batching keeps vector arrays small; hashing is instant and API-backed
        # backends stay within their provider's request limits.
        for start in range(0, len(records), batch_size):
            batch = records[start : start + batch_size]
            vectors = embedder.embed([record["text"] for record in batch])
            for record, vector in zip(batch, vectors):
                points.append(
                    {
                        "id": record["id"],
                        "vector": vector.tolist(),
                        "payload": {
                            "document_id": record["document_id"],
                            "workspace_id": workspace_id,
                            "chunk_index": record["chunk_index"],
                            "text": record["text"],
                            "metadata": record["metadata"],
                            "filename": filename,
                        },
                    }
                )

        get_store().upsert(points)
        db.insert_chunks(records, **scoped)
        if db.get_document(document_id, **scoped) is None:
            # A delete or replace raced this ingestion. Remove what this task
            # wrote so no orphan chunks or vectors can be retrieved later.
            db.delete_chunks_by_document(document_id, **scoped)
            get_store().delete_document(document_id, **scoped)
            logger.info(
                "ingestion discarded document=%s (deleted during indexing)", document_id
            )
            return
        db.update_document(
            document_id,
            status="completed",
            chunks_count=len(records),
            completed_at=db.now_iso(),
            error_message=None,
            **scoped,
        )
        logger.info(
            "ingested document=%s chunks=%d bytes=%d in %.1fs",
            document_id,
            len(records),
            len(content),
            time.perf_counter() - started,
        )
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure
        logger.warning(
            "ingestion failed document=%s bytes=%d after %.1fs: %s",
            document_id,
            len(content),
            time.perf_counter() - started,
            exc,
        )
        db.update_document(
            document_id,
            status="failed",
            error_message=INGESTION_FAILURE_DETAIL,
            **scoped,
        )
        # A failure after `upsert` can leave vectors that no chunk row points to,
        # so a retry must start from a clean slate.
        try:
            db.delete_chunks_by_document(document_id, **scoped)
            get_store().delete_document(document_id, **scoped)
        except Exception:  # noqa: BLE001 - cleanup must not mask the real error
            logger.warning("cleanup after failed ingestion document=%s failed", document_id)
