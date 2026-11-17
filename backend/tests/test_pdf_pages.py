"""PDF page labels: cite the label from the PDF tree, keep physical page honest."""

from __future__ import annotations

import io

import pypdf
from pypdf import PdfReader, PdfWriter

from app import agents
from app.ingestion import (
    ExtractedPage,
    _build_chunks,
    _extract_pdf,
    _pdf_page_labels,
)


# --------------------------------------------------------------------------- #
# Real PDF /PageLabels tree
# --------------------------------------------------------------------------- #
def _labelled_pdf(**label_args) -> bytes:
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=200, height=200)
    writer.set_page_label(0, 1, **label_args)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_page_labels_are_read_from_the_pdf_tree():
    reader = PdfReader(io.BytesIO(_labelled_pdf(style="/D", prefix="A-", start=3)))
    assert _pdf_page_labels(reader) == ["A-3", "A-4"]


def test_broken_or_missing_label_tree_is_not_fatal():
    class _Reader:
        @property
        def page_labels(self):
            raise ValueError("damaged page label tree")

    assert _pdf_page_labels(_Reader()) == []


# --------------------------------------------------------------------------- #
# Extraction: labels from the PDF tree only, honest nulls (no inference)
# --------------------------------------------------------------------------- #
class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    def __init__(self, texts: list[str], labels: list[str] | None = None) -> None:
        self.pages = [_Page(text) for text in texts]
        self._labels = labels

    @property
    def page_labels(self):
        if self._labels is None:
            raise ValueError("no label tree")
        return self._labels


def _extract(monkeypatch, texts: list[str], labels: list[str] | None = None):
    reader = _Reader(texts, labels)
    monkeypatch.setattr(pypdf, "PdfReader", lambda _stream: reader)
    return _extract_pdf(b"ignored")


def test_pdf_page_labels_are_attached_to_their_physical_page(monkeypatch):
    texts = ["cover", "preface", "body one", "body two"]
    labels = ["i", "ii", "1", "2"]

    pages = _extract(monkeypatch, texts, labels)

    assert [(page.page_number, page.page_label) for page in pages] == [
        (1, "i"),
        (2, "ii"),
        (3, "1"),
        (4, "2"),
    ]


def test_labels_equal_to_the_physical_page_are_dropped(monkeypatch):
    pages = _extract(monkeypatch, ["one", "two"], ["1", "2"])
    assert [page.page_label for page in pages] == [None, None]


def test_printed_numbers_are_not_inferred_without_a_pdf_label_tree(monkeypatch):
    """Page inference is cancelled: a printed number in the text is ignored."""
    texts = ["front matter"] * 8 + ["1\nbody", "2\nbody", "3\nbody", "4\nbody"]

    pages = _extract(monkeypatch, texts)

    # Physical pages still recorded; no labels inferred from text.
    assert [page.page_number for page in pages[8:]] == [9, 10, 11, 12]
    assert [page.page_label for page in pages] == [None] * len(pages)


def test_arabic_indic_number_in_text_is_not_inferred(monkeypatch):
    """Even a clear running number must not be turned into a page label."""
    texts = ["front matter"] * 5 + ["\u0663\nbody", "\u0664\nbody", "\u0665\nbody"]

    pages = _extract(monkeypatch, texts)

    assert [page.page_label for page in pages] == [None] * len(pages)


def test_no_label_tree_means_all_labels_are_null(monkeypatch):
    pages = _extract(monkeypatch, ["one", "two", "7", "four"])

    assert [page.page_label for page in pages] == [None] * 4


# --------------------------------------------------------------------------- #
# Chunk metadata and citations
# --------------------------------------------------------------------------- #
def test_chunks_carry_the_page_label_without_losing_the_physical_page():
    pages = [ExtractedPage(page_number=38, text="fact", page_label="30")]

    records = _build_chunks("doc-1", pages)

    assert records[0]["metadata"] == {"page_number": 38, "page_label": "30"}


def test_chunks_without_a_label_only_carry_the_physical_page():
    pages = [ExtractedPage(page_number=5, text="fact")]

    records = _build_chunks("doc-1", pages)

    assert records[0]["metadata"] == {"page_number": 5}


def test_citations_expose_the_page_label():
    chunks = [
        {
            "chunk_id": "c1",
            "document_id": "doc-1",
            "document_filename": "book.pdf",
            "chunk_index": 0,
            "text": "fact",
            "score": 0.9,
            "metadata": {"page_number": 38, "page_label": "30"},
        }
    ]

    citation = agents.build_citations(chunks)[0]

    assert citation["page_number"] == 38
    assert citation["page_label"] == "30"
