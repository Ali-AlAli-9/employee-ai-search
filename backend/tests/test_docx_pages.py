"""DOCX page numbers: explicit breaks, rendered breaks and honest nulls."""

from __future__ import annotations

import io

import docx
from docx.oxml import OxmlElement

from app.ingestion import _build_chunks, extract_pages


def _docx_bytes(build) -> bytes:
    document = docx.Document()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_explicit_page_break_splits_pages():
    def build(document):
        document.add_paragraph("page one text")
        document.add_page_break()
        document.add_paragraph("page two text")

    pages = extract_pages("report.docx", _docx_bytes(build))
    assert [(page.page_number, page.text) for page in pages] == [
        (1, "page one text"),
        (2, "page two text"),
    ]


def test_rendered_page_break_advances_the_counter():
    def build(document):
        document.add_paragraph("first page")
        paragraph = document.add_paragraph()
        run = paragraph.add_run()
        run._r.append(OxmlElement("w:lastRenderedPageBreak"))
        run.add_text("second page")

    pages = extract_pages("report.docx", _docx_bytes(build))
    assert [page.page_number for page in pages] == [1, 2]
    assert pages[0].text == "first page"
    assert pages[1].text == "second page"


def test_docx_without_breaks_does_not_invent_pages():
    def build(document):
        document.add_paragraph("only page of text")

    pages = extract_pages("report.docx", _docx_bytes(build))
    assert len(pages) == 1
    assert pages[0].page_number is None
    assert pages[0].text == "only page of text"


def test_tables_follow_the_current_page():
    def build(document):
        document.add_paragraph("before the table")
        document.add_page_break()
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "threshold"
        table.cell(0, 1).text = "0.32"

    pages = extract_pages("report.docx", _docx_bytes(build))
    by_page = {page.page_number: page.text for page in pages}
    assert by_page[1] == "before the table"
    assert "threshold | 0.32" in by_page[2]


def test_chunks_inherit_page_numbers():
    body = " ".join(f"fact {index}" for index in range(400))

    def build(document):
        document.add_paragraph(body)
        document.add_page_break()
        document.add_paragraph(body)

    pages = extract_pages("report.docx", _docx_bytes(build))
    records = _build_chunks("doc-1", pages)
    numbers = {record["metadata"]["page_number"] for record in records}
    assert numbers == {1, 2}
